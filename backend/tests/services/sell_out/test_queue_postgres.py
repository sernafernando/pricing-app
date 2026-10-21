"""The `sell_out_dirty` queue (sell-in-sell-out T7 S3): which campaigns a change
queues, the upsert that resets a re-queued campaign, and the notify.

Postgres only (`pg_notify`, `ON CONFLICT`, `SKIP LOCKED`). Runs in a throwaway
schema (`_world`).
"""

from __future__ import annotations

import select
from datetime import date
from typing import Iterator

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.services.sell_out import queue
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

D = date
ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}  # reaches 2964 only


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_queue") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _en_cola(engine: Engine, lines) -> None:
    with sessionmaker(bind=engine)() as db:
        queue.enqueue_ventas(db, lines)
        db.commit()


class TestEnqueue:
    def test_a_requeue_resets_attempts_and_moves_the_version(self, engine: Engine) -> None:
        cid = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        w.execute(
            engine,
            "INSERT INTO sell_out_dirty (campana_id, enqueued_at, attempts, last_error) "
            "VALUES (:c, now() - interval '1 hour', 5, 'roto')",
            c=cid,
        )
        with sessionmaker(bind=engine)() as db:
            antes = db.execute(queue._CLAIM_ONE_SQL.bindparams(max_attempts=99, id=cid)).scalar()
            queue.enqueue(db, [cid, cid, 999_999])  # a duplicate and an id that no longer exists
            db.commit()
            despues = db.execute(queue._CLAIM_ONE_SQL.bindparams(max_attempts=99, id=cid)).scalar()

        assert w.queued(engine) == [(cid, 0, None)]
        assert despues > antes

    def test_it_notifies_the_channel_at_commit_and_only_when_something_was_queued(self, engine: Engine) -> None:
        cid = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        listener = engine.raw_connection()
        try:
            listener.driver_connection.autocommit = True
            listener.cursor().execute(f"LISTEN {queue.CHANNEL}")
            with sessionmaker(bind=engine)() as db:
                queue.enqueue(db, [999_999])  # nothing to queue
                db.commit()
                queue.enqueue(db, [cid])
                db.commit()
            select.select([listener.driver_connection], [], [], 2)
            listener.driver_connection.poll()
            assert [n.channel for n in listener.driver_connection.notifies] == ["sell_out_dirty"]
        finally:
            listener.invalidate()  # never hand an autocommit connection back to the pool


class TestLockTimeout:
    def test_the_previous_lock_timeout_is_restored_after_the_block(self, engine: Engine) -> None:
        with sessionmaker(bind=engine)() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            with queue.lock_timeout(db, "100ms"):
                assert db.execute(text("SHOW lock_timeout")).scalar() == "100ms"

            assert db.execute(text("SHOW lock_timeout")).scalar() == "5s"


class TestFanOut:
    def test_a_sale_queues_the_active_campaigns_reaching_its_product_and_day(self, engine: Engine) -> None:
        routers = w.grupo(engine, [ROUTERS])
        cubre = w.campana(engine, [routers])
        w.campana(engine, [routers], desde=D(2026, 12, 1), hasta=D(2026, 12, 31))  # another range
        w.campana(engine, [w.grupo(engine, [{"item_id": 950}])])  # another product
        w.campana(engine, [routers], estado="anulada")
        ml = w.venta(engine, "ml", 2964, 1, D(2026, 11, 30))
        fuera = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 1))
        tn = w.venta(engine, "tn", 2964, 1, D(2026, 11, 15))

        for line in (("ml", ml), ("fuera", fuera), ("tn", tn)):
            w.clear_queue(engine)
            _en_cola(engine, [line])
            assert w.queued(engine) == [(cubre, 0, None)], line

    def test_each_sale_is_matched_to_the_range_on_its_own_day(self, engine: Engine) -> None:
        w.campana(engine, [w.grupo(engine, [ROUTERS, {"item_id": 950}])])  # November
        antes = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 15))
        despues = w.venta(engine, "fuera", 950, 1, D(2026, 12, 15))

        _en_cola(engine, [("fuera", antes), ("fuera", despues)])  # together they span November

        assert w.queued(engine) == []

    def test_a_return_inside_the_range_queues_it_and_one_after_the_end_does_not(self, engine: Engine) -> None:
        cid = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        dentro = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 20), signo=-1)
        despues = w.venta(engine, "fuera", 2964, 1, D(2026, 12, 2), signo=-1)

        _en_cola(engine, [("fuera", despues)])
        assert w.queued(engine) == []
        _en_cola(engine, [("fuera", dentro)])
        assert w.queued(engine) == [(cid, 0, None)]

    def test_a_cancelled_or_moved_sale_queues_the_campaigns_it_held(self, engine: Engine) -> None:
        cid = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        ref = w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        moved = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 3))
        for canal, venta_ref in (("ml", ref), ("fuera", moved)):
            w.execute(
                engine,
                "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
                "VALUES (:c, :canal, :r, 2964, '2026-11-02', 1, 10)",
                c=cid,
                canal=canal,
                r=venta_ref,
            )
        w.delete_venta(engine, "ml", ref)  # cancelled: the line is gone
        w.execute(  # moved out of the range: its current day reaches nothing
            engine,
            "UPDATE ventas_fuera_ml_metricas SET fecha_venta = '2027-01-05 00:00+00' WHERE it_transaction = :r",
            r=moved,
        )

        for line in (("ml", ref), ("fuera", moved)):
            w.clear_queue(engine)
            _en_cola(engine, [line])
            assert w.queued(engine) == [(cid, 0, None)], line

    def test_the_day_is_the_utc_date_of_the_sale(self, engine: Engine) -> None:
        cid = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        ref = w.venta(engine, "tn", 2964, 1, D(2026, 11, 1))
        # 21:30 in Buenos Aires on Oct 31 is Nov 1 in UTC: inside the range, as `alcance.ventas` reads it.
        w.execute(
            engine,
            "UPDATE ventas_tienda_nube_metricas SET fecha_venta = '2026-10-31 21:30-03' WHERE it_transaction = :r",
            r=ref,
        )
        with sessionmaker(bind=engine)() as db:
            db.execute(text("SET LOCAL timezone = 'America/Argentina/Buenos_Aires'"))
            queue.enqueue_ventas(db, [("tn", ref)])
            db.commit()

        assert w.queued(engine) == [(cid, 0, None)]

    def test_a_batch_of_lines_costs_a_fixed_number_of_queries(self, engine: Engine) -> None:
        routers = w.grupo(engine, [ROUTERS])
        ids = [w.campana(engine, [routers]) for _ in range(3)]
        lines = [
            (canal, w.venta(engine, canal, 2964, 1, D(2026, 11, d)))
            for d in range(1, 9)
            for canal in ("ml", "fuera", "tn")
        ]
        statements = []

        def _count(conn, cursor, statement, *args) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", _count)
        try:
            _en_cola(engine, lines)
        finally:
            event.remove(engine, "before_cursor_execute", _count)

        assert [q[0] for q in w.queued(engine)] == ids
        # consumptions + one per channel + reach + the upsert, whatever the number of lines
        assert len(statements) == 6

    def test_no_lines_or_no_reach_queue_nothing(self, engine: Engine) -> None:
        w.campana(engine, [w.grupo(engine, [ROUTERS])])
        ref = w.venta(engine, "fuera", 950, 1, D(2026, 11, 2))

        _en_cola(engine, [])
        _en_cola(engine, [("fuera", ref), ("fuera", 123)])  # 123: a line already gone, holding nothing

        assert w.queued(engine) == []


class TestBna:
    def test_queues_unrated_al_cobro_and_sale_day_campaigns_still_running(self, engine: Engine) -> None:
        g = w.grupo(engine, [ROUTERS])
        usd = {"moneda": "USD"}
        sin_tasa = w.campana(engine, [g], desde=D(2026, 10, 1), hasta=D(2026, 10, 31), tc_modo="al_cobro", **usd)
        w.campana(
            engine,
            [g],
            desde=D(2026, 10, 1),
            hasta=D(2026, 10, 31),
            tc_modo="al_cobro",
            tipo_cambio="1400",
            **usd,
            tc_definido_en="2026-11-01 10:00+00",
        )  # rated and over: nothing moves
        corriendo = w.campana(engine, [g], tc_modo="dia_venta", **usd)
        w.campana(
            engine, [g], desde=D(2026, 10, 1), hasta=D(2026, 10, 31), tc_modo="dia_venta", **usd
        )  # over before the rate
        w.campana(engine, [g])  # ARS
        w.campana(engine, [g], tc_modo="al_cobro", estado="anulada", **usd)
        w.campana(engine, [g], tc_modo="fijo", tipo_cambio="1400", **usd)  # running, but its rate is its own
        w.campana(
            engine, [g], tc_modo="al_cobro", tipo_cambio="1400", tc_definido_en="2026-11-01 10:00+00", **usd
        )  # running, rate defined: BNA no longer moves it

        with sessionmaker(bind=engine)() as db:
            queue.enqueue_por_bna(db, D(2026, 11, 10))
            db.commit()

        assert [q[0] for q in w.queued(engine)] == [sin_tasa, corriendo]
