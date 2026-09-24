"""RED/GREEN -- `read_stored_metrics` / `metrics_state_for_orders`, the
reader path over already-stored Gauss metrics (ventas-ml-rediseno PR7.T1,
design D2/D9/D13). Never recomputes: seeds real stored rows via
`recompute_order_metrics` (the actual producer/writer), then asserts the
reader returns exactly what was stored -- no live formula call involved.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.models.varios_venta_pct import VariosVentaPct
from app.services.order_metrics.queue import POISON_THRESHOLD
from app.services.order_metrics.read import metrics_state_for_orders, read_stored_metrics
from app.services.order_metrics.store import recompute_order_metrics
from app.services.order_metrics.types import GaussStatus


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


def _varios(db) -> None:
    db.add(VariosVentaPct(porcentaje=Decimal("0.00"), fecha_desde=date(2020, 1, 1), fecha_hasta=None))


def _fully_costed_order(db, order_id: int) -> None:
    _order(db, order_id)
    db.add(
        MlPaymentOps(
            payment_id=order_id,
            order_id=order_id,
            status="approved",
            net_received_amount=Decimal("121.00"),
        )
    )
    db.add(MlOrderItemOps(order_id=order_id, item_id="MLA1", seller_sku="SKU-1", quantity=1))
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id="MLA1",
            costo_origen=Decimal("10.00"),
            moneda="ARS",
            costo_unitario_ars=Decimal("10.00"),
            iva_pct=Decimal("21.00"),
            precio_unitario=Decimal("121.00"),
            fuente="sku",
            producto_item_id=1,
        )
    )
    _varios(db)


class TestReadStoredMetrics:
    def test_order_with_no_stored_row_is_absent_never_fabricated(self, db):
        _order(db, 70001)
        db.commit()

        result = read_stored_metrics(db, [70001])

        assert 70001 not in result

    def test_stored_row_is_returned_verbatim_never_recomputed_live(self, db):
        """Seed a fully-costed order, store its metrics once via the real
        producer, then MUTATE the underlying payment data so a fresh live
        recompute would answer differently. `read_stored_metrics` must
        still return the ORIGINALLY STORED value -- proof it never
        recomputes."""
        order_id = 70002
        _fully_costed_order(db, order_id)
        db.commit()
        recompute_order_metrics(db, [order_id])
        db.commit()

        stored_before = read_stored_metrics(db, [order_id])[order_id]
        assert stored_before.total_gauss == Decimal("90.00")

        # Mutate the input AFTER the store -- a live recompute would now
        # see a different net amount.
        db.query(MlPaymentOps).filter(MlPaymentOps.order_id == order_id).update(
            {"net_received_amount": Decimal("999999.00")}
        )
        db.commit()

        stored_after = read_stored_metrics(db, [order_id])[order_id]
        assert stored_after.total_gauss == Decimal("90.00"), "must read the STORED value, never recompute live"

    def test_lineas_reconstructed_from_ml_venta_deducciones(self, db):
        order_id = 70003
        _fully_costed_order(db, order_id)
        db.commit()
        recompute_order_metrics(db, [order_id])
        db.commit()

        stored = read_stored_metrics(db, [order_id])[order_id]

        assert stored.lineas, "chain lines must be reconstructed from ml_venta_deducciones"
        codes = [code for code, _monto, _concepto in stored.lineas]
        assert "costo_mercaderia" in codes


class TestMetricsStateForOrders:
    def test_no_stored_row_no_dirty_row_is_pending(self, db):
        _order(db, 70010)
        db.commit()

        result = metrics_state_for_orders(db, [70010])

        assert result[70010] == "pending"

    def test_stored_row_no_dirty_row_reflects_gauss_status(self, db):
        order_id = 70011
        _fully_costed_order(db, order_id)
        db.commit()
        recompute_order_metrics(db, [order_id])
        db.commit()

        result = metrics_state_for_orders(db, [order_id])

        assert result[order_id] == GaussStatus.OK.value

    def test_dirty_row_below_threshold_is_recalculating_even_with_a_stored_row(self, db):
        order_id = 70012
        _fully_costed_order(db, order_id)
        db.commit()
        recompute_order_metrics(db, [order_id])
        db.add(MlOrderMetricsDirty(order_id=order_id, reason="test"))
        db.commit()

        result = metrics_state_for_orders(db, [order_id])

        assert result[order_id] == "recalculating"

    def test_parked_dirty_row_is_failed_never_recalculating(self, db):
        """A parked order (attempts >= POISON_THRESHOLD) is never shown as
        `recalculating` forever -- nothing will retry it (design D9)."""
        order_id = 70013
        _order(db, order_id)
        db.add(MlOrderMetricsDirty(order_id=order_id, reason="test", attempts=POISON_THRESHOLD))
        db.commit()

        result = metrics_state_for_orders(db, [order_id])

        assert result[order_id] == "failed"

    def test_parked_wins_over_a_stale_stored_ok_row(self, db):
        order_id = 70014
        _fully_costed_order(db, order_id)
        db.commit()
        recompute_order_metrics(db, [order_id])
        db.add(MlOrderMetricsDirty(order_id=order_id, reason="test", attempts=POISON_THRESHOLD))
        db.commit()

        result = metrics_state_for_orders(db, [order_id])

        assert result[order_id] == "failed"
