"""`sell.drain` (sell-in-sell-out T5): claims queued sale lines and recomputes
the sell-in allocation of every product they touch (their queued product and,
through their stored consumptions, the product they were filed under before),
then acks them.

Postgres only: the queue is claimed with `FOR UPDATE SKIP LOCKED` and fed by
the live triggers. Runs in a throwaway schema (`tests.services.sell_in._world`).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.sell_out import (
    SellOutCampana,
    SellOutCampanaGrupo,
    SellOutCampanaItem,
    SellOutConsumo,
    SellOutDirty,
    SellOutPrograma,
)
from app.services.sell import queue
from app.services.sell_in import costing
from app.workers.context import WorkerContext
from app.workers.handlers import sell_drain
from app.workers.handlers.sell_drain import drain as handler
from app.workers.handlers.sell_out_drain import drain as sell_out_drain
from app.workers.registry import REGISTRY
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _world as w

D = date
_PRODUCTS_OF = queue.products_of


# The drain also queues the sell-out campaigns its lines can move (T7 S3).
SELL_OUT_TABLES = [
    t.__table__
    for t in (
        OffsetGrupo,
        OffsetGrupoFiltro,
        SellOutPrograma,
        SellOutCampana,
        SellOutCampanaGrupo,
        SellOutCampanaItem,
        SellOutConsumo,
        SellOutDirty,
    )
]
# `sell_out_campanas.offset_origen_id` references the legacy offsets (T15).
SELL_OUT_STUBS = ["CREATE TABLE offsets_ganancia (id INTEGER PRIMARY KEY)"]


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema(
        "sell_drain", [*w.TABLES, *SELL_OUT_TABLES], [*w.STUBS, *SELL_OUT_STUBS], after=w.install
    ) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _db(monkeypatch: pytest.MonkeyPatch, engine: Engine) -> Iterator[None]:
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
    yield
    w.clean(engine)
    with engine.begin() as conn:  # the sell-out side: links, consumptions and queue cascade
        conn.execute(text("DELETE FROM sell_out_campanas"))
        conn.execute(text("DELETE FROM offset_grupos"))


def _campana(engine: Engine, desde: date = D(2026, 10, 1), hasta: date = D(2026, 10, 31)) -> int:
    """An ARS per-unit sell-out campaign (10 per unit, no cap) over product 2964."""
    with engine.begin() as conn:
        grupo = conn.execute(text("INSERT INTO offset_grupos (nombre) VALUES ('G') RETURNING id")).scalar()
        conn.execute(text("INSERT INTO offset_grupo_filtros (grupo_id, item_id) VALUES (:g, 2964)"), {"g": grupo})
        cid = conn.execute(
            text(
                "INSERT INTO sell_out_campanas (nombre, fecha_desde, fecha_hasta, tipo, monto_unit, moneda, "
                "usuario_id) VALUES ('C', :d, :h, 'por_unidad', 10, 'ARS', 7) RETURNING id"
            ),
            {"d": desde, "h": hasta},
        ).scalar()
        conn.execute(
            text("INSERT INTO sell_out_campana_grupos (campana_id, grupo_id) VALUES (:c, :g)"), {"c": cid, "g": grupo}
        )
    return cid


def _sell_out(engine: Engine, sql: str) -> list:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql))]


def _ctx() -> WorkerContext:
    return WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="w")


def _drain():
    result = handler.run(_ctx())
    assert result.success
    return result.detail


@pytest.mark.postgres
class TestDrain:
    def test_it_is_registered_and_woken_by_its_channel(self) -> None:
        assert handler in REGISTRY
        assert handler.name == "sell.drain"
        assert handler.channels == (queue.CHANNEL,) == ("sell_dirty",)
        assert handler.interval is None and handler.run_at_local is None

    def test_a_drained_line_queues_the_sell_out_campanas_it_can_move(self, engine: Engine) -> None:
        octubre = _campana(engine)
        _campana(engine, D(2026, 11, 1), D(2026, 11, 30))
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 16))
        w.venta(engine, "tn", 950, 1, D(2026, 11, 2))  # a product no campaign reaches

        _drain()

        assert _sell_out(engine, "SELECT campana_id FROM sell_out_dirty") == [(octubre,)]
        assert w.queued(engine) == []

    def test_a_drained_sale_is_allocated_to_no_lot_and_gets_no_cost_bonus(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sell-in-costo-si T5 PR A: costo SI replaced the FIFO lots (S14) and holds the loyalty through its invoices
        (L24: "no podemos descontarselo dos veces"), so the drain only acks the line."""
        from app.services.sell_in import bonos_costo

        w.compra(engine, [(2964, 10, "250000.00")])
        w.venta(engine, "fuera", 2964, 2, D(2026, 10, 16))
        llamados = []
        monkeypatch.setattr(bonos_costo, "recalcular", lambda *a, **k: llamados.append(a))

        detail = _drain()

        assert w.consumos(engine) == []
        assert w.queued(engine) == []
        assert llamados == []
        assert (detail["lines"], detail["inserted"], detail["deleted"], detail["failed"]) == (1, 0, 0, 0)

    def test_it_drains_in_batches(self, engine: Engine) -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sell_dirty (canal, venta_ref, item_id) "
                    "SELECT 'fuera', g, 950 FROM generate_series(1, :n) AS g"
                ),
                {"n": queue.BATCH_SIZE + 3},
            )

        detail = _drain()

        assert (detail["lines"], detail["batches"]) == (queue.BATCH_SIZE + 3, 2)
        assert w.queued(engine) == []

    def test_an_empty_queue_is_one_cheap_pass(self) -> None:
        assert _drain() == {"lines": 0, "batches": 0, "products": 0, "inserted": 0, "deleted": 0, "failed": 0}


@pytest.mark.postgres
class TestConcurrency:
    def test_a_line_locked_by_another_drain_is_skipped_not_waited_for(self, engine: Engine) -> None:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES ('fuera', 1, 950)"))
            conn.execute(text("INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES ('fuera', 2, 950)"))
        with engine.connect() as other:
            other.execute(text("SELECT 1 FROM sell_dirty WHERE venta_ref = 1 FOR UPDATE"))

            detail = _drain()

            other.rollback()

        assert detail["lines"] == 1
        assert w.queued(engine) == [("fuera", 1)]


@pytest.mark.postgres
class TestPoison:
    def test_a_line_that_keeps_failing_is_parked(self, engine: Engine) -> None:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO sell_dirty (canal, venta_ref, item_id, attempts) VALUES ('fuera', 1, 950, :n)"),
                {"n": queue.MAX_ATTEMPTS},
            )

        assert _drain()["lines"] == 0
        assert w.queued(engine) == [("fuera", 1)]


def _set_attempts(engine: Engine, ref: int, attempts: int) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE sell_dirty SET attempts = :n WHERE venta_ref = :r"), {"n": attempts, "r": ref})


def _errors(caplog: pytest.LogCaptureFixture):
    """The park alerts (ERROR); `logger.exception` tracebacks are ERROR too and are left out."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == sell_drain.__name__ and r.levelno == logging.ERROR and "parked" in r.getMessage()
    ]


def _fails_2964(monkeypatch: pytest.MonkeyPatch) -> None:
    escribir = costing.FifoPurchaseCosting._escribir

    def _falla(db, item_id, deseados, guardados):
        if item_id == 2964:
            raise RuntimeError("boom")
        return escribir(db, item_id, deseados, guardados)

    monkeypatch.setattr(costing.FifoPurchaseCosting, "_escribir", staticmethod(_falla))


@pytest.mark.postgres
class TestObservability:
    """A systemic bug would charge every line and park the whole queue: a run
    that charges says how many, and a line that parks is an ERROR (alerting)."""

    def test_a_line_that_parks_in_the_line_by_line_retry_logs_an_error(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        _set_attempts(engine, ref, queue.MAX_ATTEMPTS - 1)

        def _falla(db, claimed):
            raise RuntimeError("boom")

        monkeypatch.setattr(queue, "products_of", _falla)

        with caplog.at_level(logging.WARNING, logger=sell_drain.__name__):
            _drain()

        assert _attempts(engine, ref) == queue.MAX_ATTEMPTS
        [error] = _errors(caplog)
        assert f"line fuera/{ref} parked after {queue.MAX_ATTEMPTS} attempts" in error

    def test_no_park_error_when_the_batch_commit_fails(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        w.compra(engine, [(2964, 3, "30.00")])
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        _set_attempts(engine, ref, queue.MAX_ATTEMPTS - 1)
        _fails_2964(monkeypatch)
        _commit_fails_on(monkeypatch, {1})

        with caplog.at_level(logging.WARNING, logger=sell_drain.__name__):
            _drain()

        assert _attempts(engine, ref) == queue.MAX_ATTEMPTS - 1  # the charge was rolled back
        assert _errors(caplog) == []

    def test_no_park_error_when_the_line_retry_commit_fails(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        w.compra(engine, [(2964, 3, "30.00")])
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        _set_attempts(engine, ref, queue.MAX_ATTEMPTS - 1)
        _fails_2964(monkeypatch)
        calls = []

        def _batch_fails_once(db, claimed):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("batch boom")
            return _PRODUCTS_OF(db, claimed)

        monkeypatch.setattr(queue, "products_of", _batch_fails_once)
        _commit_fails_on(monkeypatch, {2})  # 1: the batch, 2: the line's own retry

        with caplog.at_level(logging.WARNING, logger=sell_drain.__name__):
            _drain()

        assert _attempts(engine, ref) == queue.MAX_ATTEMPTS - 1
        assert _errors(caplog) == []


def _commit_fails_on(monkeypatch: pytest.MonkeyPatch, which: set) -> None:
    """The n-th `get_background_db()` block (1-based, in `which`) fails at commit
    with a lost connection, after its body ran: everything it wrote rolls back."""
    real = sell_drain.get_background_db
    opened = []

    @contextmanager
    def _db():
        opened.append(1)
        n = len(opened)
        with real() as db:
            yield db
            if n in which:
                raise _db_error(None, cls=OperationalError)

    monkeypatch.setattr(sell_drain, "get_background_db", _db)


def _attempts(engine: Engine, ref: int):
    with engine.connect() as conn:
        return conn.execute(text("SELECT attempts FROM sell_dirty WHERE venta_ref = :r"), {"r": ref}).scalar()


def _park(engine: Engine, ref: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE sell_dirty SET attempts = :n WHERE venta_ref = :r"), {"n": queue.MAX_ATTEMPTS, "r": ref}
        )


@pytest.mark.postgres
class TestBatchFailure:
    """An error outside the per-product savepoint (finding the lines' products,
    a recompute that does not isolate it, acking) rolls the whole batch back.
    The drain then retries the batch line by line, so only the line that causes
    it is charged, and that line is parked after `queue.MAX_ATTEMPTS` runs."""

    @pytest.fixture
    def mala(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> int:
        w.compra(engine, [(2964, 3, "30.00"), (2270, 3, "30.00")])
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        products_of = queue.products_of

        def _falla(db, claimed):
            if any(r == ref for _, r, _ in claimed):
                raise RuntimeError("boom")
            return products_of(db, claimed)

        monkeypatch.setattr(queue, "products_of", _falla)
        return ref

    def test_a_transient_error_while_charging_stops_the_run_and_leaves_the_line_uncharged(
        self, engine: Engine, mala: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _charge_loses_the_connection(db, line, error, enqueued_at):
            raise _db_error(None, cls=OperationalError)

        monkeypatch.setattr(queue, "charge", _charge_loses_the_connection)

        detail = _drain()

        assert detail["failed"] == 0
        assert (w.queued(engine), _attempts(engine, mala)) == ([("fuera", mala)], 0)

    def test_a_requeue_between_the_failure_and_its_charge_is_not_charged(
        self, engine: Engine, mala: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened = []
        real = sell_drain.get_background_db

        def _db():
            opened.append(1)
            if len(opened) == 3:  # batch, mala's retry, then the charge: the sale changes right before it
                w.update_venta(engine, "fuera", mala, monto_total=Decimal("60000.00"))
            return real()

        monkeypatch.setattr(sell_drain, "get_background_db", _db)

        detail = _drain()

        # batch, retry, charge, then the costo SI queue check after the sale lines (sell-in-costo-si T2) and the
        # ML re-freeze queue check (T3 PR 7)
        assert (detail["lines"], len(opened)) == (1, 5)
        assert w.queued(engine) == [("fuera", mala)]
        assert _attempts(engine, mala) == 0  # the fresh re-queue, not the failed version


class _PgError(Exception):
    def __init__(self, pgcode):
        super().__init__(f"pg {pgcode}")
        self.pgcode = pgcode


def _db_error(pgcode, cls=DBAPIError, invalidated=False):
    return cls("SELECT 1", {}, _PgError(pgcode), connection_invalidated=invalidated)


class TestTransientClassification:
    @pytest.mark.parametrize("pgcode", ["40P01", "40001", "55P03", "08006", "08003"])
    def test_deadlock_serialization_lock_and_connection_sqlstates_are_transient(self, pgcode: str) -> None:
        assert sell_drain.is_transient(_db_error(pgcode))

    def test_an_invalidated_connection_and_a_codeless_operational_error_are_transient(self) -> None:
        assert sell_drain.is_transient(_db_error(None, invalidated=True))
        assert sell_drain.is_transient(_db_error(None, cls=OperationalError))

    @pytest.mark.parametrize("pgcode", ["23505", "22P02", "54001", "57014", None])
    def test_data_errors_and_statement_timeouts_are_not_transient(self, pgcode) -> None:
        assert not sell_drain.is_transient(_db_error(pgcode))

    def test_a_python_error_is_not_transient(self) -> None:
        assert not sell_drain.is_transient(RuntimeError("boom"))

    def test_an_unsynced_combo_bill_of_materials_is_transient(self) -> None:
        # Nothing wrong with the lines: they stay queued, uncharged, until the combos sync fills the table.
        from app.services.combos.componentes import CombosNoSincronizados

        assert sell_drain.is_transient(CombosNoSincronizados())


@pytest.mark.postgres
class TestTransientFailure:
    """An infrastructure error is nobody's fault: nothing is charged, the run
    stops, and the next wake retries the lines as they were."""

    @pytest.fixture
    def falla(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> dict:
        w.compra(engine, [(2964, 3, "30.00"), (2270, 3, "30.00")])
        state = {"error": _db_error("40P01")}
        products_of = queue.products_of

        def _falla(db, claimed):
            if state["error"] is not None:
                raise state["error"]
            return products_of(db, claimed)

        monkeypatch.setattr(queue, "products_of", _falla)
        return state

    def test_a_deadlock_charges_nothing_and_the_next_wake_drains(self, engine: Engine, falla: dict) -> None:
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))

        detail = _drain()

        assert (detail["lines"], detail["failed"]) == (0, 0)
        assert (w.queued(engine), _attempts(engine, ref)) == ([("fuera", ref)], 0)
        falla["error"] = None
        assert _drain()["lines"] == 1
        assert w.queued(engine) == []

    def test_a_transient_error_on_the_line_retry_stops_the_run_uncharged(
        self, engine: Engine, falla: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primera = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        segunda = w.venta(engine, "fuera", 2270, 1, D(2026, 10, 3))
        falla["error"] = RuntimeError("boom")  # the batch fails as a whole...
        claim_line = queue.claim_line

        def _reclaim(db, line):
            falla["error"] = _db_error(None, cls=OperationalError)  # ...and its retry loses the connection
            return claim_line(db, line)

        monkeypatch.setattr(queue, "claim_line", _reclaim)

        detail = _drain()

        assert detail["failed"] == 0
        assert (_attempts(engine, primera), _attempts(engine, segunda)) == (0, 0)

    def test_a_data_error_is_still_charged(self, engine: Engine, falla: dict) -> None:
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        falla["error"] = _db_error("22P02")

        assert _drain()["failed"] == 1
        assert _attempts(engine, ref) == 1


@pytest.mark.postgres
class TestRevival:
    """A parked line comes back when its sale changes again: every writer
    re-queues it with `attempts = 0`."""


@pytest.mark.postgres
class TestSellOutFanOut:
    def test_a_cancelled_line_queues_the_campaign_holding_it_and_its_rows_drop(self, engine: Engine) -> None:
        cid = _campana(engine)
        ref = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 16))
        _drain()
        sell_out_drain.run(_ctx())
        consumos = "SELECT campana_id, venta_ref, unidades FROM sell_out_consumos"
        assert _sell_out(engine, consumos) == [(cid, ref, 2)]

        w.delete_venta(engine, "fuera", ref)  # cancelled: only its consumptions still point at the campaign
        _drain()
        assert _sell_out(engine, "SELECT campana_id FROM sell_out_dirty") == [(cid,)]
        sell_out_drain.run(_ctx())

        assert _sell_out(engine, consumos) == []
