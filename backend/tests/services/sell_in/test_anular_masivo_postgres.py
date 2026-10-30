"""Bulk void of purchases on a real Postgres: every purchase goes through the single void, and the per-product
advisory locks its recomputes take are taken up front, in item_id order, so a bulk void never deadlocks a drain or
another bulk void that touches the same products in another order."""

from __future__ import annotations

import threading
import time
from typing import Iterator

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.models.sell_in import SellInCompra, SellInCompraItem
from app.services.sell_in import anular_masivo, compras
from tests.services.sell_in import _world as w

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_in_anular_masivo") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _compra_de(engine: Engine, lineas) -> int:
    (linea, *_) = w.compra(engine, lineas)
    with sessionmaker(bind=engine)() as db:
        return db.get(SellInCompraItem, linea).compra_id


def _anular(db, ids):
    return anular_masivo.anular_varios(
        db,
        ids,
        lambda compra_id: compras.anular_compra_sin_commit(db, compra_id, 7, None, es_masivo=True),
        ya_anulada=compras.SellInYaAnulada,
        rechazos=(compras.SellInGenerada,),
        no_existe=lambda compra_id: f"La compra {compra_id} no existe",
        preparar=lambda: compras.bloquear_productos_de(db, ids),
    )


def test_the_locks_of_every_product_are_taken_first_in_item_id_order(engine):
    # Purchase A holds the higher item, B the lower one: one recompute per purchase alone would lock 2964 then 950.
    a = _compra_de(engine, [(2964, 2, "100.00")])
    b = _compra_de(engine, [(950, 2, "100.00"), (2270, 1, "50.00")])
    locks = []
    with sessionmaker(bind=engine)() as db:
        conn = db.connection()

        @event.listens_for(conn, "before_cursor_execute")
        def _capturar(_conn, _cursor, statement, parameters, _context, _many):
            if "pg_advisory_xact_lock" in statement:
                locks.append(list(parameters["ids"]))

        assert _anular(db, [a, b]) == ([a, b], [])

    assert locks[0] == [950, 2270, 2964]
    with sessionmaker(bind=engine)() as db:
        assert {db.get(SellInCompra, x).estado for x in (a, b)} == {"anulada"}


def test_the_purchase_rows_are_locked_in_id_order_before_the_product_locks(engine):
    # The single void locks its purchase row, then (in its recompute) the products: the bulk one keeps that order, or a
    # single void and a bulk void of the same purchase would each wait on the lock the other holds.
    a = _compra_de(engine, [(2964, 2, "100.00")])
    b = _compra_de(engine, [(950, 2, "100.00")])
    sentencias = []
    with sessionmaker(bind=engine)() as db:
        conn = db.connection()

        @event.listens_for(conn, "before_cursor_execute")
        def _capturar(_conn, _cursor, statement, parameters, _context, _many):
            if "pg_advisory_xact_lock" in statement:
                sentencias.append("productos")
            elif "FOR UPDATE" in statement and "sell_in_compras" in statement:
                sentencias.append(("compras", statement, parameters))

        _anular(db, [b, a])

    (primera, *_) = sentencias
    assert primera != "productos"
    assert sentencias.index("productos") == 1
    _, statement, _ = primera
    assert "ORDER BY sell_in_compras.id" in statement


def test_a_refused_bulk_void_leaves_the_released_units_where_they_were(engine):
    # The first purchase's recompute releases its units before the missing one is reached: the rollback must undo it.
    a = _compra_de(engine, [(2964, 5, "100.00")])
    w.venta(engine, "fuera", 2964, 2, w.date(2026, 10, 5))
    with sessionmaker(bind=engine)() as db:
        compras.get_costing().recompute(db, [2964])
        db.commit()
    antes = w.consumos(engine)
    assert antes

    with sessionmaker(bind=engine)() as db, pytest.raises(anular_masivo.AnulacionRechazada):
        _anular(db, [a, 424242])

    assert w.consumos(engine) == antes
    with sessionmaker(bind=engine)() as db:
        assert db.get(SellInCompra, a).estado != "anulada"


def test_a_deadlock_with_another_writer_refuses_the_whole_bulk_void_with_a_retry(engine):
    # Another transaction holds product 950's lock; the bulk void takes A's row and waits on 950; the other one then
    # updates A's row: a lock cycle Postgres breaks by aborting the bulk void (40P01). Nothing is voided, and the
    # caller gets a refusal it can retry, never a 500.
    a = _compra_de(engine, [(950, 2, "100.00")])
    resultado: list = []
    pid: list = []

    def bulk() -> None:
        with sessionmaker(bind=engine)() as db:
            pid.append(db.execute(text("SELECT pg_backend_pid()")).scalar())
            try:
                resultado.append(_anular(db, [a]))
            except Exception as exc:  # noqa: BLE001 - asserted below
                resultado.append(exc)

    with engine.connect() as otra:
        tx = otra.begin()
        otra.execute(compras.LOCK_SQL, {"ns": compras.LOCK_NAMESPACE, "ids": [950]})
        hilo = threading.Thread(target=bulk)
        hilo.start()
        _esperar_bloqueado(engine, pid)
        otra.execute(text("UPDATE sell_in_compras SET descripcion = descripcion WHERE id = :a"), {"a": a})
        tx.rollback()
        hilo.join(timeout=30)

    (exc,) = resultado
    assert isinstance(exc, anular_masivo.AnulacionRechazada) and exc.reintentar
    # It deadlocks while taking the rows and products up front, before voiding any purchase: none is singled out.
    assert (exc.ocupada, exc.rechazadas) == (None, [])
    with sessionmaker(bind=engine)() as db:
        assert db.get(SellInCompra, a).estado == "activa"


def _esperar_bloqueado(engine: Engine, pid: list) -> None:
    """Waits (bounded) until the bulk void's backend is waiting on a lock."""
    sql = text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p")
    for _ in range(100):
        if pid:
            with engine.connect() as conn:
                if conn.execute(sql, {"p": pid[0]}).scalar() == "Lock":
                    return
        time.sleep(0.05)
    raise AssertionError("the bulk void never waited on the other transaction's lock")
