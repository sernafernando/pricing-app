"""`sell.drain` (sell-in-sell-out T4): INERT until T5. It claims queued sale
lines and acks them without computing any allocation.

Postgres only: the queue is claimed with `FOR UPDATE SKIP LOCKED`. Runs in a
throwaway schema holding the queue and the sell-in allocation tables.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Tuple

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.models.sell_dirty import SellDirty
from app.models.sell_in import SellInCompra, SellInCompraItem, SellInConsumo
from app.services.sell import queue
from app.workers.context import WorkerContext
from app.workers.handlers.sell_drain import drain as handler
from app.workers.registry import REGISTRY
from tests.services.sell._schema import throwaway_schema


# Bare stand-ins for what the sell-in tables reference.
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE proveedores (id INTEGER PRIMARY KEY)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY)",
    "CREATE TABLE productos_erp (item_id INTEGER PRIMARY KEY)",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO productos_erp VALUES (2964)",
]
# Every allocation table that exists so far (sell out lands in T6).
_ALLOCATION = [SellInCompra.__table__, SellInCompraItem.__table__, SellInConsumo.__table__]


@pytest.fixture(scope="module")
def pg_sell_drain_engine() -> Iterator[Engine]:
    with throwaway_schema("sell_drain", [*_ALLOCATION, SellDirty.__table__], _STUBS) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _db(monkeypatch: pytest.MonkeyPatch, pg_sell_drain_engine: Engine) -> Iterator[None]:
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=pg_sell_drain_engine))
    yield
    with pg_sell_drain_engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))
        conn.execute(text("DELETE FROM sell_in_compras"))  # cascades to items and consumptions


def _seed_allocation(engine: Engine) -> None:
    """One purchase, its item and a consumption by a sale that is also queued."""
    with engine.begin() as conn:
        compra = conn.execute(
            text(
                "INSERT INTO sell_in_compras (fecha_compra, moneda, monto_total, usuario_id) "
                "VALUES (DATE '2026-10-01', 'ARS', 250000.00, 7) RETURNING id"
            )
        ).scalar()
        item = conn.execute(
            text(
                "INSERT INTO sell_in_compra_items (compra_id, item_id, cantidad, costo_base_unit, monto_asignado) "
                "VALUES (:c, 2964, 10, 41081.895750, 250000.00) RETURNING id"
            ),
            {"c": compra},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO sell_in_consumos (compra_item_id, canal, venta_ref, item_id, fecha_venta, unidades, "
                "descuento_ars) VALUES (:i, 'fuera', 590274, 2964, DATE '2026-10-16', 1, 25000.00)"
            ),
            {"i": item},
        )


def _allocation_snapshot(engine: Engine) -> List[list]:
    with engine.connect() as conn:
        return [
            [tuple(row) for row in conn.execute(text(f"SELECT * FROM {table.name} ORDER BY id"))]
            for table in _ALLOCATION
        ]


def _queue(engine: Engine, *lines: Tuple[str, int, int]) -> None:
    with engine.begin() as conn:
        for canal, ref, item in lines:
            conn.execute(
                text("INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES (:c, :r, :i)"),
                {"c": canal, "r": ref, "i": item},
            )


def _queued(engine: Engine) -> List[int]:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT venta_ref FROM sell_dirty ORDER BY venta_ref"))]


def _ctx() -> WorkerContext:
    return WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="w")


@pytest.mark.postgres
class TestInertDrain:
    def test_it_is_registered_and_woken_by_its_channel(self) -> None:
        assert handler in REGISTRY
        assert handler.name == "sell.drain"
        assert handler.channels == (queue.CHANNEL,) == ("sell_dirty",)
        assert handler.interval is None and handler.run_at_local is None

    def test_it_acks_every_queued_line_in_batches(self, pg_sell_drain_engine: Engine) -> None:
        canales = ("ml", "fuera", "tn")
        _queue(pg_sell_drain_engine, *((canales[n % 3], 590_000 + n, 2964) for n in range(queue.BATCH_SIZE + 3)))

        result = handler.run(_ctx())

        assert result.success
        assert result.detail == {"acked": queue.BATCH_SIZE + 3, "batches": 2}
        assert _queued(pg_sell_drain_engine) == []

    def test_it_acks_the_queue_and_leaves_every_allocation_table_untouched(self, pg_sell_drain_engine: Engine) -> None:
        _seed_allocation(pg_sell_drain_engine)
        _queue(pg_sell_drain_engine, ("fuera", 590274, 2964), ("ml", 81001, 2964), ("tn", 589254, 2270))
        before = _allocation_snapshot(pg_sell_drain_engine)

        result = handler.run(_ctx())

        assert result.detail == {"acked": 3, "batches": 1}
        assert _queued(pg_sell_drain_engine) == []
        assert _allocation_snapshot(pg_sell_drain_engine) == before
        assert all(before), "every allocation table was seeded"

    def test_an_empty_queue_is_one_cheap_pass(self) -> None:
        result = handler.run(_ctx())

        assert result.success and result.detail == {"acked": 0, "batches": 0}

    def test_a_line_locked_by_another_drain_is_skipped_not_waited_for(self, pg_sell_drain_engine: Engine) -> None:
        _queue(pg_sell_drain_engine, ("fuera", 1, 950), ("fuera", 2, 950))
        with pg_sell_drain_engine.connect() as other:
            other.execute(text("SELECT 1 FROM sell_dirty WHERE venta_ref = 1 FOR UPDATE"))

            with sessionmaker(bind=pg_sell_drain_engine)() as s:
                acked = queue.ack_batch(s, queue.BATCH_SIZE)
                s.commit()

            other.rollback()

        assert acked == [("fuera", 2, 950)]
        assert _queued(pg_sell_drain_engine) == [1]
