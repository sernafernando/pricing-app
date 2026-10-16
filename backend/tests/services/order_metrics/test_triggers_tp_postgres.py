"""The recompute trigger on `ml_order_item_costos` also fires when a TP cost
is set (metricas-ml-tplink-mode P3): P2's backfill and late-load worker fill
a NULL `costo_tp_*` with an UPDATE, and the order's stored TP figures must be
recomputed through the same dirty queue as any other cost change. A write
that leaves the TP cost unchanged still enqueues nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

ORDER_ID = 310901

_FILL_TP = (
    "UPDATE ml_order_item_costos SET costo_tp_origen = 8, costo_tp_moneda = 'ARS', "
    "costo_tp_unitario_ars = 8, costo_tp_fuente = 'lista8_historia', costo_tp_at = now() "
    "WHERE order_id = :order_id"
)


def _dirty_reason(session):
    return session.execute(
        text("SELECT reason FROM ml_order_metrics_dirty WHERE order_id = :order_id"), {"order_id": ORDER_ID}
    ).scalar()


def _clear_dirty(session) -> None:
    session.execute(text("DELETE FROM ml_order_metrics_dirty"))
    session.commit()


@pytest.fixture()
def order_with_cost(pg_order_metrics_triggers_db):
    session = pg_order_metrics_triggers_db
    session.execute(
        text(
            "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created) "
            "VALUES (:order_id, 999, 'paid', :at, :at)"
        ),
        {"order_id": ORDER_ID, "at": datetime(2026, 8, 20, tzinfo=timezone.utc)},
    )
    session.execute(
        text(
            "INSERT INTO ml_order_item_costos (order_id, item_id, costo_origen, moneda, costo_unitario_ars, "
            "iva_pct, precio_unitario, fuente, producto_item_id) "
            "VALUES (:order_id, 'MLA1', 10, 'ARS', 10, 21, 100, 'sku', 1)"
        ),
        {"order_id": ORDER_ID},
    )
    session.commit()
    _clear_dirty(session)
    yield session
    session.execute(text("DELETE FROM ml_order_item_costos WHERE order_id = :order_id"), {"order_id": ORDER_ID})
    session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :order_id"), {"order_id": ORDER_ID})
    session.commit()
    _clear_dirty(session)


@pytest.mark.postgres
class TestTpCostEnqueuesRecompute:
    def test_filling_a_null_tp_cost_enqueues_the_order(self, order_with_cost) -> None:
        session = order_with_cost

        session.execute(text(_FILL_TP), {"order_id": ORDER_ID})
        session.commit()

        assert _dirty_reason(session) == "ml_order_item_costos_update"

    def test_rewriting_the_same_tp_cost_enqueues_nothing(self, order_with_cost) -> None:
        session = order_with_cost
        session.execute(text(_FILL_TP), {"order_id": ORDER_ID})
        session.commit()
        _clear_dirty(session)

        session.execute(
            text("UPDATE ml_order_item_costos SET costo_tp_unitario_ars = 8 WHERE order_id = :order_id"),
            {"order_id": ORDER_ID},
        )
        session.commit()

        assert _dirty_reason(session) is None
