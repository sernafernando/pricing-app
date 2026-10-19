"""`rrhh.horas_extras`: the daily overtime (HE) detection, run by the main worker at 03:30 local
time instead of a crontab entry.

A run processes every Argentina day from the cursor `worker_job_state.detail.last_day_done` + 1 through
yesterday, oldest first, at most 7 per run (with no cursor, only yesterday), then purges old read
alerts. The cursor advances in the same transaction as each day's detection, so a day that fails is
retried, even after midnight, instead of being skipped."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.rrhh_horas_extras import RRHHHorasExtrasConfig
from app.models.worker_job_state import WorkerJobState
from app.services import rrhh_horas_extras_diario as diario
from app.workers.context import WorkerContext
from app.workers.handlers import rrhh_horas_extras as module
from app.workers.handlers.rrhh_horas_extras import RRHHHorasExtrasHandler, horas_extras
from app.workers.registry import REGISTRY
from tests.routers.test_rrhh_horas_extras_recalcular_lock import held, is_held

DETECTION = {"procesados": 3, "creados": 2, "actualizados": 1, "alertas": 0, "errores": 0, "pendientes_turno": 0}
PURGE = {"purgadas": 4, "retenidas": 9}
NAME = "rrhh.horas_extras"


class _Sessions:
    """Session factory that hands out the test session and records which blocks failed."""

    def __init__(self, db) -> None:
        self.db = db
        self.opened = 0
        self.failed = 0

    @contextmanager
    def __call__(self):
        self.opened += 1
        try:
            yield self.db
        except Exception:
            self.failed += 1
            raise


class _FakeService:
    calls: list[tuple] = []
    failing_days: set[date] = set()
    purge_error: Exception | None = None
    probe = None  # optional callable run during each detection (e.g. a lock probe)
    probes: list = []

    def __init__(self, db) -> None:
        self.db = db

    def detectar_he_periodo(self, desde: date, hasta: date, commit: bool = True) -> dict[str, int]:
        _FakeService.calls.append(("detect", desde, hasta, commit))
        if _FakeService.probe is not None:
            _FakeService.probes.append(_FakeService.probe())
        if desde in _FakeService.failing_days:
            raise RuntimeError(f"detection exploded on {desde}")
        return dict(DETECTION)

    def purgar_alertas_viejas(self) -> dict[str, int]:
        _FakeService.calls.append(("purge",))
        if _FakeService.purge_error is not None:
            raise _FakeService.purge_error
        return dict(PURGE)


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch) -> type[_FakeService]:
    _FakeService.calls = []
    _FakeService.failing_days = set()
    _FakeService.purge_error = None
    _FakeService.probe = None
    _FakeService.probes = []
    monkeypatch.setattr(diario, "HorasExtrasService", _FakeService)
    return _FakeService


def _detected(service) -> list[date]:
    return [call[1] for call in service.calls if call[0] == "detect"]


def _config(db, *, cron_activo: bool) -> None:
    db.add(RRHHHorasExtrasConfig(id=1, cron_activo=cron_activo))
    db.flush()


def _set_cursor(db, day: date, **other) -> None:
    db.add(WorkerJobState(name=NAME, detail={"last_day_done": day.isoformat(), **other}))
    db.flush()


def _cursor(db) -> str | None:
    db.expire_all()
    row = db.get(WorkerJobState, NAME)
    return (row.detail or {}).get("last_day_done") if row else None


def _ctx() -> WorkerContext:
    return WorkerContext(deadline=datetime.now(UTC) + timedelta(seconds=30), worker_name="w")


def _handler(db, now: datetime) -> tuple[RRHHHorasExtrasHandler, _Sessions]:
    sessions = _Sessions(db)
    return RRHHHorasExtrasHandler(session_factory=sessions, now=lambda: now), sessions


# 2026-10-19 12:00 UTC is 09:00 in Argentina, so yesterday is 2026-10-18.
NOON = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
YESTERDAY = date(2026, 10, 18)


class TestRegistration:
    def test_it_is_a_daily_0330_job_of_the_main_worker(self) -> None:
        assert horas_extras in REGISTRY
        assert horas_extras.name == NAME
        assert horas_extras.channels == ()
        assert horas_extras.interval is None
        assert horas_extras.run_at_local == time(3, 30)


class TestDisabled:
    def test_cron_activo_false_touches_nothing(self, db, service) -> None:
        _config(db, cron_activo=False)
        handler, _ = _handler(db, NOON)

        result = handler.run(_ctx())

        assert result.success is False
        assert result.detail == {"disabled": True}
        assert service.calls == []
        assert _cursor(db) is None

    def test_a_missing_config_row_counts_as_disabled(self, db, service) -> None:
        handler, _ = _handler(db, NOON)

        result = handler.run(_ctx())

        assert result.detail == {"disabled": True}
        assert service.calls == []


class TestDays:
    @pytest.mark.parametrize(
        ("now", "expected_day"),
        [
            # 02:59 UTC on the 19th is 23:59 on the 18th in Argentina: yesterday is the 17th.
            (datetime(2026, 10, 19, 2, 59, tzinfo=UTC), date(2026, 10, 17)),
            # 03:00 UTC on the 19th is 00:00 on the 19th in Argentina: yesterday is the 18th.
            (datetime(2026, 10, 19, 3, 0, tzinfo=UTC), date(2026, 10, 18)),
            (NOON, YESTERDAY),
        ],
    )
    def test_without_a_cursor_it_processes_only_the_previous_argentina_day(
        self, db, service, now, expected_day
    ) -> None:
        _config(db, cron_activo=True)
        handler, _ = _handler(db, now)

        result = handler.run(_ctx())

        assert result.success is True
        assert service.calls == [("detect", expected_day, expected_day, False), ("purge",)]
        assert result.detail == {
            "days": [expected_day.isoformat()],
            "detections": {expected_day.isoformat(): DETECTION},
            "purge": PURGE,
        }
        assert _cursor(db) == expected_day.isoformat()

    def test_it_catches_up_from_the_cursor_oldest_first(self, db, service) -> None:
        _config(db, cron_activo=True)
        _set_cursor(db, date(2026, 10, 15))
        handler, _ = _handler(db, NOON)

        result = handler.run(_ctx())

        assert result.success is True
        assert _detected(service) == [date(2026, 10, 16), date(2026, 10, 17), YESTERDAY]
        assert result.detail["days"] == ["2026-10-16", "2026-10-17", "2026-10-18"]
        assert _cursor(db) == "2026-10-18"

    def test_at_most_seven_days_per_run(self, db, service) -> None:
        _config(db, cron_activo=True)
        _set_cursor(db, date(2026, 10, 1))
        handler, _ = _handler(db, NOON)

        handler.run(_ctx())

        assert _detected(service) == [date(2026, 10, d) for d in range(2, 9)]
        assert _cursor(db) == "2026-10-08"

    def test_an_up_to_date_cursor_does_nothing(self, db, service) -> None:
        _config(db, cron_activo=True)
        _set_cursor(db, YESTERDAY)
        handler, _ = _handler(db, NOON)

        result = handler.run(_ctx())

        assert result.success is True
        assert result.detail == {"days": []}
        assert service.calls == []

    def test_the_cursor_merges_into_the_existing_detail(self, db, service) -> None:
        _config(db, cron_activo=True)
        _set_cursor(db, date(2026, 10, 17), other="kept")
        handler, _ = _handler(db, NOON)

        handler.run(_ctx())

        db.expire_all()
        assert db.get(WorkerJobState, NAME).detail == {"last_day_done": "2026-10-18", "other": "kept"}


class TestFailures:
    def test_a_purge_failure_keeps_the_detection(self, db, service) -> None:
        _config(db, cron_activo=True)
        service.purge_error = RuntimeError("purge exploded")
        handler, sessions = _handler(db, NOON)

        result = handler.run(_ctx())

        assert result.success is True
        assert result.error is None
        assert result.detail["detections"] == {"2026-10-18": DETECTION}
        assert result.detail["purge_error"] == "RuntimeError: purge exploded"
        assert "purge" not in result.detail
        assert _cursor(db) == "2026-10-18"
        # cursor read, config read, the day and the purge each ran in their own session; only the purge failed
        assert (sessions.opened, sessions.failed) == (4, 1)

    def test_a_failed_day_stops_the_run_and_keeps_the_cursor_before_it(self, db, service) -> None:
        _config(db, cron_activo=True)
        _set_cursor(db, date(2026, 10, 15))
        service.failing_days = {date(2026, 10, 17)}
        handler, _ = _handler(db, NOON)

        result = handler.run(_ctx())

        assert result.success is False
        assert result.error == "RuntimeError: detection exploded on 2026-10-17"
        assert result.detail == {
            "days": ["2026-10-16"],
            "failed_day": "2026-10-17",
            "error": "RuntimeError: detection exploded on 2026-10-17",
        }
        assert _detected(service) == [date(2026, 10, 16), date(2026, 10, 17)]
        assert ("purge",) not in service.calls
        assert _cursor(db) == "2026-10-16"

    def test_a_raw_database_error_taking_the_lock_fails_with_the_retry_delay(self, db, service, monkeypatch) -> None:
        _config(db, cron_activo=True)

        def broken_lock(session):
            raise OperationalError("SELECT pg_try_advisory_xact_lock", {}, Exception("connection lost"))

        monkeypatch.setattr(diario, "try_detection_lock", broken_lock)
        clock = [NOON]
        handler = RRHHHorasExtrasHandler(session_factory=_Sessions(db), now=lambda: clock[0])

        result = handler.run(_ctx())

        assert result.success is False
        assert "connection lost" in result.error
        assert service.calls == []
        clock[0] = NOON + timedelta(minutes=5)
        assert handler.run(_ctx()).detail == {"retry_at": (NOON + timedelta(minutes=15)).isoformat()}


class TestRetryAcrossMidnight:
    def test_a_day_that_failed_before_midnight_is_processed_after_it(self, db, service) -> None:
        # The run for the 17th fails at 23:50 on the 18th (Argentina); the retry lands after midnight,
        # when "yesterday" is already the 18th. The 17th must still be processed, then the 18th.
        _config(db, cron_activo=True)
        _set_cursor(db, date(2026, 10, 16))
        service.failing_days = {date(2026, 10, 17)}
        clock = [datetime(2026, 10, 19, 2, 50, tzinfo=UTC)]  # 23:50 on the 18th in Argentina
        handler = RRHHHorasExtrasHandler(session_factory=_Sessions(db), now=lambda: clock[0])

        assert handler.run(_ctx()).success is False
        assert _cursor(db) == "2026-10-16"

        service.failing_days = set()
        clock[0] = datetime(2026, 10, 19, 3, 10, tzinfo=UTC)  # 00:10 on the 19th, past the retry delay
        result = handler.run(_ctx())

        assert result.success is True
        assert result.detail["days"] == ["2026-10-17", "2026-10-18"]
        assert _detected(service) == [date(2026, 10, 17), date(2026, 10, 17), date(2026, 10, 18)]
        assert _cursor(db) == "2026-10-18"


class TestRetryDelay:
    def test_a_failed_detection_waits_before_the_next_try(self, db, service) -> None:
        # A failed daily job stays due on every worker pass (seconds apart); the handler spaces the retries.
        _config(db, cron_activo=True)
        service.failing_days = {YESTERDAY}
        clock = [NOON]
        handler = RRHHHorasExtrasHandler(session_factory=_Sessions(db), now=lambda: clock[0])
        handler.run(_ctx())

        clock[0] = NOON + timedelta(minutes=5)
        waiting = handler.run(_ctx())
        assert waiting.success is False
        assert waiting.error == "RuntimeError: detection exploded on 2026-10-18"
        assert waiting.detail["retry_at"] == (NOON + timedelta(minutes=15)).isoformat()
        assert len(_detected(service)) == 1

        service.failing_days = set()
        clock[0] = NOON + timedelta(minutes=15)
        assert handler.run(_ctx()).success is True
        assert len(_detected(service)) == 2


# --- Postgres: the advisory lock and the cursor upsert, for real ----------------------------------


@pytest.fixture()
def pg_sessions(pg_worker_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """Real committing sessions on `worker_job_state` (config gate stubbed: no RRHH tables here)."""
    monkeypatch.setattr(diario, "_cron_activo", lambda db: True)
    with pg_worker_engine.begin() as conn:
        conn.execute(text("DELETE FROM worker_job_state WHERE name = :name"), {"name": NAME})
    yield pg_worker_engine
    with pg_worker_engine.begin() as conn:
        conn.execute(text("DELETE FROM worker_job_state WHERE name = :name"), {"name": NAME})


def _pg_factory(engine: Engine):
    @contextmanager
    def factory():
        with Session(bind=engine) as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    return factory


def _pg_detail(engine: Engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT detail FROM worker_job_state WHERE name = :name"), {"name": NAME}).scalar()


@pytest.mark.postgres
class TestPostgresLock:
    def test_the_day_runs_holding_the_lock_and_releases_it_at_commit(self, pg_sessions, service) -> None:
        service.probe = lambda: is_held(pg_sessions)
        handler = RRHHHorasExtrasHandler(session_factory=_pg_factory(pg_sessions), now=lambda: NOON)

        assert handler.run(_ctx()).success is True

        assert service.probes == [True]
        assert is_held(pg_sessions) is False
        assert _pg_detail(pg_sessions) == {"last_day_done": "2026-10-18"}

    def test_it_skips_while_another_run_holds_the_lock(self, pg_sessions, service) -> None:
        clock = [NOON]
        handler = RRHHHorasExtrasHandler(session_factory=_pg_factory(pg_sessions), now=lambda: clock[0])

        with held(pg_sessions):
            result = handler.run(_ctx())

        assert result.success is False
        assert result.detail == {"skipped": "locked", "days": []}
        assert service.calls == []
        # the 15-minute retry delay applies to a skipped run too
        clock[0] = NOON + timedelta(minutes=5)
        assert handler.run(_ctx()).success is False
        assert service.calls == []
        clock[0] = NOON + timedelta(minutes=15)
        assert handler.run(_ctx()).success is True

    def test_the_cursor_upsert_merges_with_what_is_stored(self, pg_sessions, service) -> None:
        with pg_sessions.begin() as conn:
            conn.execute(
                text("INSERT INTO worker_job_state (name, detail) VALUES (:name, CAST(:detail AS jsonb))"),
                {"name": NAME, "detail": '{"last_day_done": "2026-10-16", "other": "kept"}'},
            )
        handler = RRHHHorasExtrasHandler(session_factory=_pg_factory(pg_sessions), now=lambda: NOON)

        assert handler.run(_ctx()).success is True

        assert _detected(service) == [date(2026, 10, 17), YESTERDAY]
        assert _pg_detail(pg_sessions) == {"last_day_done": "2026-10-18", "other": "kept"}


def test_module_exposes_the_run_limit() -> None:
    assert module.MAX_DAYS_PER_RUN == 7
