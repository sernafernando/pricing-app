"""`sell.drain` (sell-in-sell-out T5): claims queued sale lines and recomputes
the sell-in allocation of every product they touch (their queued product and,
through their stored consumptions, the product they were filed under before),
then acks them.

Postgres only: the queue is claimed with `FOR UPDATE SKIP LOCKED` and fed by
the live triggers. Runs in a throwaway schema (`tests.services.sell_in._world`).
"""

from __future__ import annotations

import threading
import time as clock
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.services.sell import queue
from app.services.sell_in import costing
from app.workers.context import WorkerContext
from app.workers.handlers import sell_drain
from app.workers.handlers.sell_drain import drain as handler
from app.workers.registry import REGISTRY
from tests.services.sell_in import _world as w

D = date
_PRODUCTS_OF = queue.products_of


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_drain") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _db(monkeypatch: pytest.MonkeyPatch, engine: Engine) -> Iterator[None]:
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
    yield
    w.clean(engine)


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

    def test_a_new_sale_is_allocated_and_leaves_the_queue(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 10, "250000.00")])
        ref = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 16))
        assert w.queued(engine) == [("fuera", ref)]

        detail = _drain()

        assert w.consumos(engine) == [(linea, "fuera", ref, 2964, 2, Decimal("50000.00"))]
        assert w.queued(engine) == []
        assert detail == {"lines": 1, "batches": 1, "products": 1, "inserted": 1, "deleted": 0, "failed": 0}

    def test_a_deleted_ml_order_frees_its_units_for_the_next_sale(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 2, "20.00")])
        primera = w.venta(engine, "ml", 2964, 2, D(2026, 10, 2))
        segunda = w.venta(engine, "tn", 2964, 2, D(2026, 10, 3))
        _drain()  # the tn sale is queued by its trigger; the ml line is recomputed with its product
        costing_now = w.consumos(engine)
        assert [c[2] for c in costing_now] == [primera]

        w.delete_venta(engine, "ml", primera)  # cascade: queued by the ml_order_items_ops trigger
        _drain()

        assert w.consumos(engine) == [(linea, "tn", segunda, 2964, 2, Decimal("20.00"))]

    def test_a_quantity_change_reallocates(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 3, "30.00")])
        primera = w.venta(engine, "fuera", 2964, 3, D(2026, 10, 2))
        segunda = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))
        _drain()

        w.update_venta(engine, "fuera", primera, cantidad=Decimal("2.0000"))
        _drain()

        assert w.consumos(engine) == [
            (linea, "fuera", primera, 2964, 2, Decimal("20.00")),
            (linea, "fuera", segunda, 2964, 1, Decimal("10.00")),
        ]

    def test_a_product_change_releases_the_old_product_found_through_its_consumptions(self, engine: Engine) -> None:
        [vieja] = w.compra(engine, [(2964, 1, "10.00")])
        ref = w.venta(engine, "tn", 2964, 1, D(2026, 10, 2))
        otra = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 3))
        _drain()
        assert [c[2] for c in w.consumos(engine)] == [ref]

        w.update_venta(engine, "tn", ref, item_id=2270)  # queued under its NEW product only
        assert w.queued(engine) == [("tn", ref)]
        _drain()

        assert w.consumos(engine) == [(vieja, "fuera", otra, 2964, 1, Decimal("10.00"))]

    def test_a_queued_return_gives_its_units_to_the_next_sale(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 1, "10.00")])
        antes = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2), cliente=31748)
        despues = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 4), cliente=202741)
        _drain()
        assert w.consumos(engine) == [(linea, "fuera", antes, 2964, 1, Decimal("10.00"))]

        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 3), signo=-1, cliente=31748)  # queued by the trigger
        _drain()

        assert w.consumos(engine) == [(linea, "fuera", despues, 2964, 1, Decimal("10.00"))]

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

    def test_two_drains_on_one_product_take_turns(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 3, "30.00")])
        primera = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 2))
        segunda = w.venta(engine, "tn", 2964, 2, D(2026, 10, 3))
        # Drain A claims the fuera line and holds the product's lock, uncommitted.
        a = sessionmaker(bind=engine)()
        outcome: dict = {}

        def _drain_b() -> None:
            try:
                outcome["detail"] = _drain()
            except BaseException as exc:  # surfaced below, not lost in the thread
                outcome["error"] = exc

        b = threading.Thread(target=_drain_b, daemon=True)
        try:
            claimed = queue.claim_batch(a, 1)
            costing.get_costing().recompute(a, [item for _, _, item in claimed])
            b.start()
            clock.sleep(0.5)
            assert b.is_alive(), "drain B waits for the product lock instead of interleaving"

            queue.settle(a, [(c, r) for c, r, _ in claimed], {})
            a.commit()
        finally:
            a.rollback()
            a.close()
        b.join(timeout=10)

        assert not b.is_alive(), "drain B never finished after drain A released the product lock"
        assert "error" not in outcome, f"drain B raised {outcome.get('error')!r}"
        assert outcome["detail"]["failed"] == 0
        assert w.consumos(engine) == [
            (linea, "fuera", primera, 2964, 2, Decimal("20.00")),
            (linea, "tn", segunda, 2964, 1, Decimal("10.00")),
        ]
        assert w.queued(engine) == []


@pytest.mark.postgres
class TestPoison:
    def test_a_failing_product_keeps_its_line_queued_and_charged(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        w.compra(engine, [(2964, 3, "30.00"), (2270, 3, "30.00")])
        mala = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        buena = w.venta(engine, "fuera", 2270, 1, D(2026, 10, 2))
        escribir = costing.FifoPurchaseCosting._escribir

        def _falla(db, item_id, deseados, guardados):
            if item_id == 2964:
                raise RuntimeError("boom")
            return escribir(db, item_id, deseados, guardados)

        monkeypatch.setattr(costing.FifoPurchaseCosting, "_escribir", staticmethod(_falla))

        detail = _drain()

        assert detail["failed"] == 1
        assert [c[2] for c in w.consumos(engine)] == [buena]
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT attempts, last_error FROM sell_dirty WHERE venta_ref = :r"), {"r": mala}
            ).one()
        assert row[0] == 1 and "boom" in row[1]

    def test_a_line_that_keeps_failing_is_parked(self, engine: Engine) -> None:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO sell_dirty (canal, venta_ref, item_id, attempts) VALUES ('fuera', 1, 950, :n)"),
                {"n": queue.MAX_ATTEMPTS},
            )

        assert _drain()["lines"] == 0
        assert w.queued(engine) == [("fuera", 1)]

    def test_a_line_charged_earlier_in_a_run_is_not_claimed_again_by_a_later_batch(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        w.compra(engine, [(2964, 3, "30.00"), (2270, 3, "30.00")])
        mala = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        buena = w.venta(engine, "fuera", 2270, 1, D(2026, 10, 2))
        escribir = costing.FifoPurchaseCosting._escribir

        def _falla(db, item_id, deseados, guardados):
            if item_id == 2964:
                raise RuntimeError("boom")
            return escribir(db, item_id, deseados, guardados)

        monkeypatch.setattr(costing.FifoPurchaseCosting, "_escribir", staticmethod(_falla))
        monkeypatch.setattr(queue, "BATCH_SIZE", 1)  # one line per batch: mala, then buena, then nothing

        detail = _drain()

        assert (detail["lines"], detail["batches"], detail["failed"]) == (2, 2, 1)
        assert [c[2] for c in w.consumos(engine)] == [buena]
        assert _attempts(engine, mala) == 1


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

    def test_only_the_line_that_breaks_its_batch_is_charged(self, engine: Engine, mala: int) -> None:
        buena = w.venta(engine, "fuera", 2270, 1, D(2026, 10, 2))

        detail = _drain()

        assert (detail["lines"], detail["failed"]) == (2, 1)
        assert [c[1:] for c in w.consumos(engine)] == [("fuera", buena, 2270, 1, Decimal("10.00"))]
        assert w.queued(engine) == [("fuera", mala)]
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT attempts, last_error FROM sell_dirty WHERE venta_ref = :r"), {"r": mala}
            ).one()
        assert row[0] == 1 and "boom" in row[1]

    def test_it_is_parked_after_max_attempts_and_later_lines_still_drain(self, engine: Engine, mala: int) -> None:
        for _ in range(queue.MAX_ATTEMPTS):
            assert _drain()["failed"] == 1

        assert _attempts(engine, mala) == queue.MAX_ATTEMPTS
        despues = w.venta(engine, "fuera", 2270, 1, D(2026, 10, 3))

        detail = _drain()

        assert (detail["lines"], detail["failed"]) == (1, 0)
        assert [c[2] for c in w.consumos(engine)] == [despues]
        assert w.queued(engine) == [("fuera", mala)]

    def test_lines_left_when_the_deadline_passes_stay_untouched_for_the_next_wake(
        self, engine: Engine, mala: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buena = w.venta(engine, "fuera", 2270, 1, D(2026, 10, 3))  # queued after mala: retried after it
        deadline = datetime.now(timezone.utc) + timedelta(seconds=0.5)
        products_of = queue.products_of

        def _slow_failure(db, claimed):
            if [r for _, r, _ in claimed] == [mala]:
                clock.sleep(0.6)  # mala's own retry outlives the deadline
            return products_of(db, claimed)

        monkeypatch.setattr(queue, "products_of", _slow_failure)

        detail = handler.run(WorkerContext(deadline=deadline, worker_name="w")).detail

        assert (detail["lines"], detail["failed"]) == (1, 1)  # buena was left untouched, not processed
        assert (_attempts(engine, mala), _attempts(engine, buena)) == (1, 0)
        assert w.consumos(engine) == []
        monkeypatch.setattr(queue, "products_of", _PRODUCTS_OF)  # mala is fixed

        assert _drain()["lines"] == 2
        assert [c[2] for c in w.consumos(engine)] == [mala, buena]
        assert w.queued(engine) == []

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

        assert (detail["lines"], len(opened)) == (1, 3)
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

    def test_a_line_whose_recompute_always_times_out_is_parked_and_the_queue_moves_on(
        self, engine: Engine, falla: dict
    ) -> None:
        lenta = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        falla["error"] = _db_error("57014")  # statement_timeout: the line's own fault, every time

        for _ in range(queue.MAX_ATTEMPTS):
            assert _drain()["failed"] == 1

        assert _attempts(engine, lenta) == queue.MAX_ATTEMPTS
        despues = w.venta(engine, "fuera", 2270, 1, D(2026, 10, 3))
        falla["error"] = None
        detail = _drain()

        assert (detail["lines"], detail["failed"]) == (1, 0)
        assert [c[2] for c in w.consumos(engine)] == [despues]
        assert w.queued(engine) == [("fuera", lenta)]

    def test_a_data_error_is_still_charged(self, engine: Engine, falla: dict) -> None:
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        falla["error"] = _db_error("22P02")

        assert _drain()["failed"] == 1
        assert _attempts(engine, ref) == 1


@pytest.mark.postgres
class TestRevival:
    """A parked line comes back when its sale changes again: every writer
    re-queues it with `attempts = 0`."""

    def test_a_change_to_a_parked_fuera_sale_revives_its_line(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 1, "10.00")])
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        _park(engine, ref)
        assert _drain()["lines"] == 0

        w.update_venta(engine, "fuera", ref, monto_total=Decimal("60000.00"))  # the trigger re-queues it
        detail = _drain()

        assert (detail["lines"], detail["failed"]) == (1, 0)
        assert w.consumos(engine) == [(linea, "fuera", ref, 2964, 1, Decimal("10.00"))]
        assert w.queued(engine) == []

    def test_a_parked_ml_line_is_revived_by_enqueue_ml(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 1, "10.00")])
        ref = w.venta(engine, "ml", 2964, 1, D(2026, 10, 2))
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES ('ml', :r, 2964)"), {"r": ref})
        _park(engine, ref)
        assert _drain()["lines"] == 0

        session = sessionmaker(bind=engine)()
        queue.enqueue_ml(session, [(ref, 2964)])  # what store_sale_lines does for a changed line
        session.commit()
        session.close()
        detail = _drain()

        assert (detail["lines"], detail["failed"]) == (1, 0)
        assert w.consumos(engine) == [(linea, "ml", ref, 2964, 1, Decimal("10.00"))]
        assert w.queued(engine) == []
