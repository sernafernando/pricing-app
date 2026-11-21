"""MLAs waiting for a "hay mejores" recompute (`worker_job_state.detail['pending_ids']` of
`ml_promotions.hay_mejores_boundaries`), written by the costo SI drain and drained by the handler.

Owner L15: "se tienen que recalcular todos los costos posteriores y los promedios claramente". Orchestrator Q8 (a):
"Append the MLAs to the handler's pending_ids atomically (row lock / jsonb update in one statement, no lost updates
with the running worker) and test the concurrent case."
"""

from __future__ import annotations

import threading
from typing import Callable, Iterator, List

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.worker_job_state import WorkerJobState
from app.services import ml_hay_mejores_pendientes as pendientes
from app.workers.handlers import ml_hay_mejores as module

pytestmark = pytest.mark.postgres

WAIT = 10  # seconds: no test can hang longer than this on a lock


@pytest.fixture()
def engine(mlpub_pg) -> Iterator[Engine]:
    from tests.conftest import _restore_pristine_pg_types

    _restore_pristine_pg_types([WorkerJobState.__table__])
    WorkerJobState.__table__.create(bind=mlpub_pg)

    @event.listens_for(mlpub_pg, "connect")
    def _lock_timeout(dbapi_conn, _record) -> None:  # a blocked statement fails instead of hanging the suite
        with dbapi_conn.cursor() as cursor:
            cursor.execute(f"SET lock_timeout = '{WAIT * 2}s'")

    mlpub_pg.dispose()  # connections opened before the listener get the setting too
    yield mlpub_pg


def _session(engine: Engine) -> Session:
    return sessionmaker(bind=engine)()


def _detail(engine: Engine) -> dict:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT detail FROM worker_job_state WHERE name = :n"), {"n": pendientes.HANDLER_NAME}
        ).scalar()


def _seed(engine: Engine, detail: dict) -> None:
    with _session(engine) as db:
        db.add(WorkerJobState(name=pendientes.HANDLER_NAME, detail=detail))
        db.commit()


def test_the_handler_reads_the_same_row() -> None:
    assert module.HANDLER_NAME == pendientes.HANDLER_NAME


def test_agregar_keeps_the_other_keys_dedups_and_sorts(engine: Engine) -> None:
    _seed(engine, {"cursor": "MLA5", "checked_until": "2026-11-13T15:00:00+00:00", "pending_ids": ["MLA3"]})
    with _session(engine) as db:
        pendientes.agregar(db, ["MLA9", "MLA1", "MLA3", "MLA9", ""])
        db.commit()
        assert pendientes.pendientes(db) == ["MLA1", "MLA3", "MLA9"]
    assert _detail(engine) == {
        "cursor": "MLA5",
        "checked_until": "2026-11-13T15:00:00+00:00",
        "pending_ids": ["MLA1", "MLA3", "MLA9"],
    }


def test_agregar_creates_the_row_when_the_handler_never_ran(engine: Engine) -> None:
    with _session(engine) as db:
        pendientes.agregar(db, ["MLA2", "MLA10"])
        db.commit()
    assert _detail(engine) == {"pending_ids": ["MLA10", "MLA2"]}  # byte order, as the handler's cursor compares


def test_no_ids_runs_no_statement(engine: Engine) -> None:
    statements: List[str] = []

    def record(_conn, _cursor, statement, *_rest) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with _session(engine) as db:
            pendientes.agregar(db, [])
            pendientes.quitar(db, [])
            db.commit()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert not [s for s in statements if "worker_job_state" in s]
    assert _detail(engine) is None


def test_quitar_removes_only_the_given_ids(engine: Engine) -> None:
    _seed(engine, {"cursor": None, "pending_ids": ["MLA1", "MLA2", "MLA3"]})
    with _session(engine) as db:
        pendientes.quitar(db, ["MLA1", "MLA3", "MLA7"])
        db.commit()
        assert pendientes.pendientes(db) == ["MLA2"]
    assert _detail(engine) == {"cursor": None, "pending_ids": ["MLA2"]}


def test_the_handler_state_write_never_touches_pending_ids(engine: Engine) -> None:
    _seed(engine, {"pending_ids": ["MLA1"]})
    with _session(engine) as db:
        module._write_state(db, {"window_until": None, "cursor": "MLA4", "checked_until": "x"})
        db.commit()
        assert pendientes.pendientes(db) == ["MLA1"]


def _in_thread(fn: Callable[[], None]) -> tuple[threading.Thread, list]:
    errors: list = []

    def target() -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - re-raised by the test
            errors.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, errors


def _worker_tick(db: Session) -> None:
    """What the handler does at the end of a chunk: state write + remove the processed pending id."""
    module._write_state(db, {"window_until": "2026-11-13T15:05:00+00:00", "cursor": "MLA1"})
    pendientes.quitar(db, ["MLA1"])


class TestConcurrentDrainAndWorker:
    """Two real connections: whichever holds the row lock first, the other waits, and nothing is lost."""

    def test_the_worker_waits_for_an_open_drain(self, engine: Engine) -> None:
        _seed(engine, {"pending_ids": ["MLA1"]})
        drain = _session(engine)
        try:
            pendientes.agregar(drain, ["MLA2"])  # holds the row lock until commit

            def worker() -> None:
                with _session(engine) as db:
                    _worker_tick(db)
                    db.commit()

            thread, errors = _in_thread(worker)
            thread.join(timeout=1)
            assert thread.is_alive(), "the worker must wait for the drain's row lock"
            drain.commit()
            thread.join(timeout=WAIT)
            assert not thread.is_alive() and not errors
        finally:
            drain.close()
        assert _detail(engine)["pending_ids"] == ["MLA2"]

    def test_the_drain_waits_for_an_open_worker(self, engine: Engine) -> None:
        _seed(engine, {"pending_ids": ["MLA1"]})
        worker = _session(engine)
        try:
            _worker_tick(worker)  # holds the row lock until commit

            def drain() -> None:
                with _session(engine) as db:
                    pendientes.agregar(db, ["MLA2"])
                    db.commit()

            thread, errors = _in_thread(drain)
            thread.join(timeout=1)
            assert thread.is_alive(), "the drain must wait for the worker's row lock"
            worker.commit()
            thread.join(timeout=WAIT)
            assert not thread.is_alive() and not errors
        finally:
            worker.close()
        assert _detail(engine)["pending_ids"] == ["MLA2"]
