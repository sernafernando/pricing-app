"""`sell_dirty` triggers (sell-in-sell-out T4): a fuera or Tienda Nube sale
that appears, changes what the allocation reads, or disappears queues its line.

Postgres only: the queue is fed by row triggers on the fuera and Tienda Nube
sale tables and woken with `pg_notify`.
The fixture rows are shaped like production rows (it_transaction, item_id,
cantidad 1.0000, fecha_venta at midnight UTC, sd_id 1, signo 1).
"""

from __future__ import annotations

import itertools
import select
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterator, List, Tuple, Type

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.ml_orders_ops import MlOrderItemOps
from app.models.ml_sale_line import MlSaleLine
from app.models.sell_dirty import SellDirty
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from app.services.sell import queue
from tests.services.sell._schema import throwaway_schema

# Children before parents in the cleanup order: `ml_sale_lines` references
# `ml_order_items_ops`.
_TABLES = [
    VentaFueraMLMetrica.__table__,
    VentaTiendaNubeMetrica.__table__,
    MlOrderItemOps.__table__,
    MlSaleLine.__table__,
    SellDirty.__table__,
]
_CANALES: List[Tuple[str, Type]] = [("fuera", VentaFueraMLMetrica), ("tn", VentaTiendaNubeMetrica)]
_ids = itertools.count(590_000)


def _install_triggers(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in queue.UPGRADE_SQL:
            conn.execute(text(statement))


@pytest.fixture(scope="module")
def pg_sell_engine() -> Iterator[Engine]:
    """Every table, the function and the triggers live in a throwaway schema:
    always installed from `queue.UPGRADE_SQL`, never inherited from (or skipped
    because of) what other tests left in the shared database."""
    with throwaway_schema("sell_dirty_trg", _TABLES, after=_install_triggers) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(pg_sell_engine: Engine) -> Iterator[None]:
    yield
    with pg_sell_engine.begin() as conn:
        for table in _TABLES:
            conn.execute(text(f"DELETE FROM {table.name}"))


def _session(engine: Engine) -> Session:
    return sessionmaker(bind=engine)()


def _queued(engine: Engine) -> List[Tuple[str, int, int]]:
    with engine.connect() as conn:
        return [
            tuple(row)
            for row in conn.execute(text("SELECT canal, venta_ref, item_id FROM sell_dirty ORDER BY canal, venta_ref"))
        ]


def _clear_queue(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))


def _venta(engine: Engine, model: Type, item_id: int = 2964, cantidad: str = "1.0000") -> int:
    it_transaction = next(_ids)
    with _session(engine) as s:
        s.add(
            model(
                it_transaction=it_transaction,
                ct_transaction=it_transaction + 1,
                item_id=item_id,
                codigo="X",
                fecha_venta=datetime(2026, 10, 16, tzinfo=timezone.utc),
                sd_id=1,
                signo=1,
                cantidad=Decimal(cantidad),
                monto_total=Decimal("54298.64"),
                costo_unitario=Decimal("41081.895750"),
                cliente="Cliente",
            )
        )
        s.commit()
    return it_transaction


def _update(engine: Engine, model: Type, ref: int, **values) -> None:
    """Updates the sale `ref` (its `it_transaction`); `values` may change the key itself."""
    sets = ", ".join(f"{column} = :{column}" for column in values)
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE {model.__tablename__} SET {sets} WHERE it_transaction = :_ref"),
            {"_ref": ref, **values},
        )


@pytest.mark.postgres
@pytest.mark.parametrize("canal,model", _CANALES)
class TestTriggers:
    def test_a_new_sale_queues_its_line_and_product(self, pg_sell_engine: Engine, canal: str, model: Type) -> None:
        ref = _venta(pg_sell_engine, model, item_id=2964)

        assert _queued(pg_sell_engine) == [(canal, ref, 2964)]

    def test_a_change_to_what_the_allocation_reads_queues_the_line(
        self, pg_sell_engine: Engine, canal: str, model: Type
    ) -> None:
        refs = [_venta(pg_sell_engine, model) for _ in range(5)]
        _clear_queue(pg_sell_engine)

        _update(pg_sell_engine, model, refs[0], cantidad=Decimal("2"))
        _update(pg_sell_engine, model, refs[1], fecha_venta=datetime(2026, 10, 1, tzinfo=timezone.utc))
        _update(pg_sell_engine, model, refs[2], monto_total=Decimal("1"))
        _update(pg_sell_engine, model, refs[3], costo_unitario=Decimal("1"))
        _update(pg_sell_engine, model, refs[4], signo=-1)

        assert [row[1] for row in _queued(pg_sell_engine)] == refs

    def test_a_product_change_queues_the_line_under_its_new_product(
        self, pg_sell_engine: Engine, canal: str, model: Type
    ) -> None:
        ref = _venta(pg_sell_engine, model, item_id=2964)
        _clear_queue(pg_sell_engine)

        _update(pg_sell_engine, model, ref, item_id=950)

        assert _queued(pg_sell_engine) == [(canal, ref, 950)]

    def test_an_update_that_changes_nothing_relevant_queues_nothing(
        self, pg_sell_engine: Engine, canal: str, model: Type
    ) -> None:
        ref = _venta(pg_sell_engine, model)
        _clear_queue(pg_sell_engine)

        # The ERP sync rewrites rows with the same values, and touches columns
        # the allocation never reads.
        _update(pg_sell_engine, model, ref, cantidad=Decimal("1.0000"), cliente="Otro", vendedor="V")

        assert _queued(pg_sell_engine) == []

    def test_a_key_change_queues_the_old_line_and_the_new_one(
        self, pg_sell_engine: Engine, canal: str, model: Type
    ) -> None:
        old = _venta(pg_sell_engine, model, item_id=2964)
        _clear_queue(pg_sell_engine)
        new = next(_ids)

        _update(pg_sell_engine, model, old, it_transaction=new, item_id=950)

        assert _queued(pg_sell_engine) == [(canal, old, 2964), (canal, new, 950)]

    def test_a_deleted_sale_queues_its_line_to_release_it(
        self, pg_sell_engine: Engine, canal: str, model: Type
    ) -> None:
        ref = _venta(pg_sell_engine, model, item_id=2267)
        _clear_queue(pg_sell_engine)

        with pg_sell_engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {model.__tablename__} WHERE it_transaction = :it"), {"it": ref})

        assert _queued(pg_sell_engine) == [(canal, ref, 2267)]

    def test_a_queued_line_is_queued_once_and_a_requeue_resets_its_attempts(
        self, pg_sell_engine: Engine, canal: str, model: Type
    ) -> None:
        ref = _venta(pg_sell_engine, model)
        with pg_sell_engine.begin() as conn:
            conn.execute(text("UPDATE sell_dirty SET attempts = 3, last_error = 'boom'"))

        _update(pg_sell_engine, model, ref, cantidad=Decimal("4"))

        with pg_sell_engine.connect() as conn:
            rows = conn.execute(text("SELECT attempts, last_error FROM sell_dirty")).all()
        assert [tuple(r) for r in rows] == [(0, None)]

    def test_the_trigger_notifies_the_channel(self, pg_sell_engine: Engine, canal: str, model: Type) -> None:
        raw = pg_sell_engine.raw_connection()
        try:
            raw.driver_connection.autocommit = True
            cursor = raw.cursor()
            cursor.execute(f"LISTEN {queue.CHANNEL}")
            _venta(pg_sell_engine, model)
            select.select([raw.driver_connection], [], [], 5)
            raw.driver_connection.poll()
            channels = [n.channel for n in raw.driver_connection.notifies]
        finally:
            # Never hand an autocommit connection back to the pool.
            raw.invalidate()

        assert queue.CHANNEL in channels


def _ml_line(engine: Engine, row_id: int, order_id: int, product: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO ml_order_items_ops (id, order_id, item_id, quantity) VALUES (:id, :o, :mla, 1)"),
            {"id": row_id, "o": order_id, "mla": f"MLA{row_id}"},
        )
        conn.execute(
            text(
                "INSERT INTO ml_sale_lines (item_row_id, order_id, group_key, product, mla, group_date, day, qty, "
                "gross, tg, tg_known, mtg, mcosto) VALUES (:id, :o, :g, :p, :mla, now(), current_date, 1, 100, 50, true, 50, 30)"
            ),
            {"id": row_id, "o": order_id, "g": f"o:{order_id}", "p": product, "mla": f"MLA{row_id}"},
        )


@pytest.mark.postgres
class TestMlCascade:
    """`ml_sale_lines.item_row_id` cascades from `ml_order_items_ops`: a deleted
    item takes its line with it, bypassing `store_sale_lines`. A BEFORE DELETE
    trigger on the item queues the line while it still exists."""

    def test_deleting_an_order_queues_its_lines_with_their_product(self, pg_sell_engine: Engine) -> None:
        _ml_line(pg_sell_engine, 81001, 2000012345, product=2964)
        _ml_line(pg_sell_engine, 81002, 2000012345, product=950)
        _ml_line(pg_sell_engine, 81003, 2000099999, product=2267)

        with pg_sell_engine.begin() as conn:
            conn.execute(text("DELETE FROM ml_order_items_ops WHERE order_id = 2000012345"))
            lines = conn.execute(text("SELECT count(*) FROM ml_sale_lines WHERE order_id = 2000012345")).scalar()

        assert lines == 0
        assert _queued(pg_sell_engine) == [("ml", 81001, 2964), ("ml", 81002, 950)]

    def test_deleting_an_item_without_a_line_queues_nothing(self, pg_sell_engine: Engine) -> None:
        with pg_sell_engine.begin() as conn:
            conn.execute(text("INSERT INTO ml_order_items_ops (id, order_id, item_id) VALUES (81010, 7, 'MLA7')"))
            conn.execute(text("DELETE FROM ml_order_items_ops WHERE id = 81010"))

        assert _queued(pg_sell_engine) == []

    def test_the_cascade_trigger_notifies_the_channel(self, pg_sell_engine: Engine) -> None:
        _ml_line(pg_sell_engine, 81020, 2000054321, product=2964)
        raw = pg_sell_engine.raw_connection()
        try:
            raw.driver_connection.autocommit = True
            cursor = raw.cursor()
            cursor.execute(f"LISTEN {queue.CHANNEL}")
            with pg_sell_engine.begin() as conn:
                conn.execute(text("DELETE FROM ml_order_items_ops WHERE id = 81020"))
            select.select([raw.driver_connection], [], [], 5)
            raw.driver_connection.poll()
            channels = [n.channel for n in raw.driver_connection.notifies]
        finally:
            raw.invalidate()

        assert queue.CHANNEL in channels
