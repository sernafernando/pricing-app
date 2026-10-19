"""`rrhh.horas_extras`: the daily overtime (HE) detection, run by the main worker at 03:30 local
time instead of a crontab entry. It processes the previous Argentina day, then purges old read alerts."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest

from app.models.rrhh_horas_extras import RRHHHorasExtrasConfig
from app.services import rrhh_horas_extras_diario as diario
from app.workers.context import WorkerContext
from app.workers.handlers.rrhh_horas_extras import RRHHHorasExtrasHandler, horas_extras
from app.workers.registry import REGISTRY
from tests.routers.test_rrhh_horas_extras_recalcular_lock import held, is_held

DETECTION = {"procesados": 3, "creados": 2, "actualizados": 1, "alertas": 0, "errores": 0, "pendientes_turno": 0}
PURGE = {"purgadas": 4, "retenidas": 9}


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


@pytest.fixture(autouse=True)
def lock_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "rrhh_he_cron.lock"
    monkeypatch.setattr(diario, "LOCK_PATHS", (path,))
    return path


class _FakeService:
    calls: list[tuple] = []
    lock_held_during_detection: list[bool] = []
    detection_error: Exception | None = None
    purge_error: Exception | None = None

    def __init__(self, db) -> None:
        self.db = db

    def detectar_he_periodo(self, desde: date, hasta: date) -> dict[str, int]:
        _FakeService.calls.append(("detect", desde, hasta))
        _FakeService.lock_held_during_detection.append(is_held(diario.LOCK_PATHS[0]))
        if _FakeService.detection_error is not None:
            raise _FakeService.detection_error
        return dict(DETECTION)

    def purgar_alertas_viejas(self) -> dict[str, int]:
        _FakeService.calls.append(("purge",))
        if _FakeService.purge_error is not None:
            raise _FakeService.purge_error
        return dict(PURGE)


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch) -> type[_FakeService]:
    _FakeService.calls = []
    _FakeService.lock_held_during_detection = []
    _FakeService.detection_error = None
    _FakeService.purge_error = None
    monkeypatch.setattr(diario, "HorasExtrasService", _FakeService)
    return _FakeService


def _config(db, *, cron_activo: bool) -> None:
    db.add(RRHHHorasExtrasConfig(id=1, cron_activo=cron_activo))
    db.flush()


def _ctx() -> WorkerContext:
    return WorkerContext(deadline=datetime.now(UTC) + timedelta(seconds=30), worker_name="w")


def _handler(db, now: datetime) -> tuple[RRHHHorasExtrasHandler, _Sessions]:
    sessions = _Sessions(db)
    return RRHHHorasExtrasHandler(session_factory=sessions, now=lambda: now), sessions


# 2026-10-19 12:00 UTC is 09:00 in Argentina, so the previous local day is 2026-10-18.
NOON = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


class TestRegistration:
    def test_it_is_a_daily_0330_job_of_the_main_worker(self) -> None:
        assert horas_extras in REGISTRY
        assert horas_extras.name == "rrhh.horas_extras"
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

    def test_a_missing_config_row_counts_as_disabled(self, db, service) -> None:
        handler, _ = _handler(db, NOON)

        result = handler.run(_ctx())

        assert result.detail == {"disabled": True}
        assert service.calls == []


class TestDetection:
    @pytest.mark.parametrize(
        ("now", "expected_day"),
        [
            # 02:59 UTC on the 19th is 23:59 on the 18th in Argentina: yesterday is the 17th.
            (datetime(2026, 10, 19, 2, 59, tzinfo=UTC), date(2026, 10, 17)),
            # 03:00 UTC on the 19th is 00:00 on the 19th in Argentina: yesterday is the 18th.
            (datetime(2026, 10, 19, 3, 0, tzinfo=UTC), date(2026, 10, 18)),
            (NOON, date(2026, 10, 18)),
        ],
    )
    def test_it_processes_the_previous_argentina_day(self, db, service, now, expected_day) -> None:
        _config(db, cron_activo=True)
        handler, _ = _handler(db, now)

        result = handler.run(_ctx())

        assert result.success is True
        assert service.calls == [("detect", expected_day, expected_day), ("purge",)]
        assert result.detail == {"day": expected_day.isoformat(), "detection": DETECTION, "purge": PURGE}

    def test_a_purge_failure_keeps_the_detection(self, db, service) -> None:
        _config(db, cron_activo=True)
        service.purge_error = RuntimeError("purge exploded")
        handler, sessions = _handler(db, NOON)

        result = handler.run(_ctx())

        assert result.success is True
        assert result.error is None
        assert result.detail["detection"] == DETECTION
        assert result.detail["purge_error"] == "RuntimeError: purge exploded"
        assert "purge" not in result.detail
        # config read, detection and purge each ran in their own session; only the purge one failed
        assert (sessions.opened, sessions.failed) == (3, 1)

    def test_a_detection_failure_fails_the_run_and_skips_the_purge(self, db, service) -> None:
        _config(db, cron_activo=True)
        service.detection_error = RuntimeError("detection exploded")
        handler, sessions = _handler(db, NOON)

        result = handler.run(_ctx())

        assert result.success is False
        assert result.error == "RuntimeError: detection exploded"
        assert result.detail == {"day": "2026-10-18", "error": "RuntimeError: detection exploded"}
        assert service.calls == [("detect", date(2026, 10, 18), date(2026, 10, 18))]
        assert (sessions.opened, sessions.failed) == (2, 1)


class TestRetryDelay:
    def test_a_failed_detection_waits_before_the_next_try(self, db, service) -> None:
        # A failed daily job stays due on every worker pass (seconds apart); the handler spaces the retries.
        _config(db, cron_activo=True)
        service.detection_error = RuntimeError("detection exploded")
        clock = [NOON]
        handler = RRHHHorasExtrasHandler(session_factory=_Sessions(db), now=lambda: clock[0])
        handler.run(_ctx())

        clock[0] = NOON + timedelta(minutes=5)
        waiting = handler.run(_ctx())
        assert waiting.success is False
        assert waiting.error == "RuntimeError: detection exploded"
        assert waiting.detail["retry_at"] == (NOON + timedelta(minutes=15)).isoformat()
        assert len(service.calls) == 1

        service.detection_error = None
        clock[0] = NOON + timedelta(minutes=15)
        assert handler.run(_ctx()).success is True
        assert len(service.calls) == 3  # the second detection, then its purge


class TestDetectionLock:
    """The worker, the manual script and `/recalcular` share one flock; the worker never overlaps them."""

    def test_the_detection_runs_holding_the_lock_and_releases_it(self, db, service, lock_path) -> None:
        _config(db, cron_activo=True)
        handler, _ = _handler(db, NOON)

        assert handler.run(_ctx()).success is True

        assert service.lock_held_during_detection == [True]
        assert is_held(lock_path) is False

    def test_it_skips_while_another_run_holds_the_lock(self, db, service, lock_path) -> None:
        _config(db, cron_activo=True)
        clock = [NOON]
        handler = RRHHHorasExtrasHandler(session_factory=_Sessions(db), now=lambda: clock[0])

        with held(lock_path):
            result = handler.run(_ctx())
            assert result.success is False
            assert result.detail == {"skipped": "locked"}
            assert service.calls == []

        # the 15-minute retry delay applies to a skipped run too
        clock[0] = NOON + timedelta(minutes=5)
        assert handler.run(_ctx()).success is False
        assert service.calls == []
        clock[0] = NOON + timedelta(minutes=15)
        assert handler.run(_ctx()).success is True

    def test_an_unusable_lock_directory_fails_clearly(self, db, service, monkeypatch, tmp_path) -> None:
        _config(db, cron_activo=True)
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        monkeypatch.setattr(diario, "LOCK_PATHS", (blocker / "rrhh_he_cron.lock",))
        handler, _ = _handler(db, NOON)

        result = handler.run(_ctx())

        assert result.success is False
        assert result.error.startswith("cannot open the HE detection lock")
        assert "not-a-dir" in result.error
        assert service.calls == []
