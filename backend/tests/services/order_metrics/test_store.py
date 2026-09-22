"""RED/GREEN -- `recompute_order_metrics` upserts `ml_order_metrics` +
`ml_venta_deducciones` + the legacy `ml_orders_ops.total_gauss*` columns, and
never commits -- the caller controls the transaction (ventas-ml-rediseno
PR1.T7, design D2, D7).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.models.ml_venta_deduccion import MlVentaDeduccion
from app.services.order_metrics.store import recompute_order_metrics


def _order(db, order_id: int) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            date_created=datetime(2026, 8, 15, tzinfo=timezone.utc),
            seller_id=999,
        )
    )


def _item_with_cost(db, order_id: int, item_id: str, quantity: int, costo_unitario_ars: Decimal) -> None:
    db.add(MlOrderItemOps(order_id=order_id, item_id=item_id, seller_sku="SKU-1", quantity=quantity))
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id=item_id,
            costo_origen=costo_unitario_ars,
            moneda="ARS",
            costo_unitario_ars=costo_unitario_ars,
            iva_pct=Decimal("21.00"),
            precio_unitario=Decimal("100.00"),
            fuente="sku",
            producto_item_id=1,
        )
    )


class TestRecomputeOrderMetricsUpserts:
    def test_inserts_metrics_row_and_legacy_columns_no_commit(self, db) -> None:
        order_id = 6001
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()

        result = recompute_order_metrics(db, [order_id])
        # No commit inside recompute_order_metrics -- flush is enough for a
        # same-session read to see the row.
        db.flush()

        row = db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).one()
        assert row.total_gauss == result[order_id].total_gauss
        assert row.gauss_status == result[order_id].gauss_status.value
        assert row.formula_version == result[order_id].formula_version

        order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).one()
        assert order.total_gauss == result[order_id].total_gauss
        assert order.total_gauss_stale is False
        assert order.total_gauss_at is not None

        deduccion_rows = db.query(MlVentaDeduccion).filter(MlVentaDeduccion.order_id == order_id).all()
        assert any(r.code == "costo_mercaderia" for r in deduccion_rows)

        db.rollback()

    def test_second_call_updates_the_same_row_instead_of_duplicating(self, db) -> None:
        order_id = 6002
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()

        recompute_order_metrics(db, [order_id])
        db.commit()

        recompute_order_metrics(db, [order_id])
        db.commit()

        rows = db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).all()
        assert len(rows) == 1

    def test_empty_order_ids_returns_empty_dict(self, db) -> None:
        assert recompute_order_metrics(db, []) == {}

    def test_unknown_order_id_is_skipped_never_inserted(self, db) -> None:
        # `ml_order_metrics.order_id` has a hard FK to `ml_orders_ops` --
        # an id with no `ml_orders_ops` row must never reach `db.add`, or
        # the flush aborts the WHOLE batch, including the real order.
        order_id = 6003
        unknown_id = 999998
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()

        result = recompute_order_metrics(db, [unknown_id, order_id])
        db.flush()  # SQLite does not enforce the FK here; the assertions below prove the skip

        assert unknown_id not in result
        assert order_id in result
        assert db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == unknown_id).one_or_none() is None
        assert db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).one_or_none() is not None

        db.rollback()
