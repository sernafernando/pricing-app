"""`combos.sync` (combos-propios C1): every 30 minutes, fetch the full combo
snapshot from the source, reconcile it against `combo_componentes` and apply
it in one short transaction. No cron."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.combo_componente import ComboComponente
from app.services.combos import fuente_erp
from app.workers.context import WorkerContext
from app.workers.handlers import combos_sync
from app.workers.handlers.combos_sync import sync as handler
from app.workers.registry import REGISTRY
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

D = Decimal
_TABLES = [ComboComponente.__table__]


@pytest.fixture()
def pg_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types(_TABLES)
    schema = f"combos_sync_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            for table in _TABLES:
                table.create(bind=conn)
        monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def _ctx(seconds: float = 30) -> WorkerContext:
    return WorkerContext(deadline=datetime.now(UTC) + timedelta(seconds=seconds), worker_name="w")


def _rows(engine: Engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT combo_item_id, componente_item_id, cantidad FROM combo_componentes "
                "ORDER BY combo_item_id, componente_item_id"
            )
        )
        return [tuple(r) for r in rows]


def _seed(engine: Engine, *rows) -> None:
    with engine.begin() as conn:
        for combo, componente, cantidad in rows:
            conn.execute(
                text("INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:a, :b, :c)"),
                {"a": combo, "b": componente, "c": cantidad},
            )


class TestRegistration:
    def test_it_is_registered_as_a_30_minute_interval_job(self) -> None:
        assert handler in REGISTRY
        assert handler.name == "combos.sync"
        assert handler.channels == ()
        assert handler.interval == timedelta(minutes=30)
        assert handler.run_at_local is None


@pytest.mark.postgres
class TestRun:
    def test_applies_the_full_snapshot(self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed(pg_engine, (100, 500, 1), (100, 600, 1), (200, 700, 1))
        monkeypatch.setattr(
            combos_sync, "fetch_snapshot", lambda timeout: {100: {500: D("2"), 601: D("1")}, 200: {700: 1}}
        )

        result = handler.run(_ctx())

        assert result.success is True
        assert result.detail == {"combos": 2, "inserted": 1, "updated": 1, "deleted": 1, "deletions_skipped": False}
        assert _rows(pg_engine) == [(100, 500, D("2")), (100, 601, D("1")), (200, 700, D("1"))]

    def test_a_failed_fetch_changes_nothing(self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed(pg_engine, (100, 500, 1))

        def boom(timeout):
            raise fuente_erp.SnapshotIncompleto("row without item_id_1")

        monkeypatch.setattr(combos_sync, "fetch_snapshot", boom)

        result = handler.run(_ctx())

        assert result.success is False
        assert "item_id_1" in result.error
        assert _rows(pg_engine) == [(100, 500, D("1"))]

    def test_a_truncated_snapshot_keeps_the_absent_combos(
        self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(pg_engine, (100, 500, 1), (200, 500, 1), (300, 500, 1))
        monkeypatch.setattr(combos_sync, "fetch_snapshot", lambda timeout: {100: {500: 3}})

        result = handler.run(_ctx())

        # Inserts/updates apply, absences are not trusted, and the run says so instead of a silent success.
        assert result.success is False
        assert "deletions skipped" in result.error
        assert result.detail["deletions_skipped"] is True
        assert _rows(pg_engine) == [(100, 500, D("3")), (200, 500, D("1")), (300, 500, D("1"))]

    def test_an_empty_snapshot_against_a_populated_table_deletes_nothing_and_fails(
        self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(pg_engine, (100, 500, 1), (200, 500, 1))
        monkeypatch.setattr(combos_sync, "fetch_snapshot", lambda timeout: {})

        result = handler.run(_ctx())

        assert result.success is False
        assert "deletions skipped" in result.error
        assert result.detail["deleted"] == 0
        assert _rows(pg_engine) == [(100, 500, D("1")), (200, 500, D("1"))]

    def test_a_past_deadline_does_not_fetch(self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        def must_not_fetch(timeout):
            raise AssertionError("fetched after the deadline")

        monkeypatch.setattr(combos_sync, "fetch_snapshot", must_not_fetch)

        result = handler.run(_ctx(seconds=-1))

        assert result.success is True
        assert result.detail == {"skipped": "deadline"}


class _ErpResponse:
    def __init__(self, chunks=(), status: int = 200) -> None:
        self.chunks, self.status = list(chunks), status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            import requests

            raise requests.exceptions.HTTPError(f"{self.status} Server Error")

    def iter_content(self, chunk_size=None):
        yield from self.chunks

    def json(self):  # what an unstreamed `requests` caller would read
        import json

        return json.loads(b"".join(self.chunks))

    def close(self) -> None:
        pass


@pytest.mark.postgres
class TestRealHelperFailure:
    """The real `fetch_item_associations_from_erp` failing (only `requests.get` is faked) writes nothing."""

    def _serve(self, monkeypatch: pytest.MonkeyPatch, response=None, error=None) -> None:
        from app.scripts import sync_item_associations as script

        def fake_get(url, params, timeout, stream=False):
            if error is not None:
                raise error
            return response

        monkeypatch.setattr(script.requests, "get", fake_get)

    @pytest.mark.parametrize(
        ("case", "expected_error"),
        [
            ("connection", "ConnectionError: refused"),
            ("http_500", "HTTPError: 500 Server Error"),
            ("bad_json", "JSONDecodeError"),
            ("unexpected_shape", "ValueError: unexpected ERP response: dict"),
            ("row_without_component", "SnapshotIncompleto: association without item_id/item_id_1"),
        ],
    )
    def test_nothing_is_written(
        self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch, case: str, expected_error: str
    ) -> None:
        import requests

        _seed(pg_engine, (100, 500, 1), (200, 500, 1))
        if case == "connection":
            self._serve(monkeypatch, error=requests.exceptions.ConnectionError("refused"))
        elif case == "http_500":
            self._serve(monkeypatch, _ErpResponse([b"[]"], status=500))
        elif case == "bad_json":
            self._serve(monkeypatch, _ErpResponse([b'[{"item_id": 1,']))
        elif case == "unexpected_shape":
            self._serve(monkeypatch, _ErpResponse([b'{"error": "boom"}']))
        else:
            self._serve(monkeypatch, _ErpResponse([b'[{"item_id": 300, "item_id_1": null, "iasso_qty": 1}]']))

        result = handler.run(_ctx())

        assert result.success is False
        assert expected_error in result.error  # this case's own failure, not a harness fault
        assert _rows(pg_engine) == [(100, 500, D("1")), (200, 500, D("1"))]

    def test_an_empty_erp_list_deletes_nothing_and_fails(
        self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(pg_engine, (100, 500, 1), (200, 500, 1))
        self._serve(monkeypatch, _ErpResponse([b"[]"]))

        result = handler.run(_ctx())

        assert result.success is False
        assert "deletions skipped" in result.error  # the reconcile floor, not a failed fetch
        assert result.detail["deletions_skipped"] is True
        assert _rows(pg_engine) == [(100, 500, D("1")), (200, 500, D("1"))]


@pytest.mark.postgres
class TestBoundedFetch:
    def _capture(self, monkeypatch: pytest.MonkeyPatch) -> list:
        timeouts: list = []

        def fake_fetch(timeout):
            timeouts.append(timeout)
            return {}

        monkeypatch.setattr(combos_sync, "fetch_snapshot", fake_fetch)
        return timeouts

    def test_the_fetch_never_waits_longer_than_the_cap(
        self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        timeouts = self._capture(monkeypatch)
        result = handler.run(_ctx(seconds=600))
        assert result.success is True
        assert timeouts == [combos_sync.FETCH_TIMEOUT_SECONDS] == [30]

    def test_the_fetch_never_outlives_the_deadline(self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        timeouts = self._capture(monkeypatch)
        result = handler.run(_ctx(seconds=12))
        assert result.success is True
        assert len(timeouts) == 1
        assert combos_sync.MIN_FETCH_SECONDS <= timeouts[0] <= 12

    def test_too_little_time_left_skips_the_run(self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        timeouts = self._capture(monkeypatch)
        result = handler.run(_ctx(seconds=combos_sync.MIN_FETCH_SECONDS - 1))
        assert timeouts == []
        assert result.detail == {"skipped": "deadline"}
