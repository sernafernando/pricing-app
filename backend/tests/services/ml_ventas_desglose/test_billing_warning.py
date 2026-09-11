"""RED -- three-case billing incompleteness reason (ml-ventas-modo-logistico
PR2, tasks 2.5/2.8).

Replaces the single condition

    has_shipment_order AND shipping_total == 0 AND not linked_detail_ids

which fired REASON_BILLING_NOT_SWEPT on Flex/Retiro sales that structurally
never receive a `shp_*` charge (see `breakdown_service` module docstring).
Three cases instead:

  (a) mode structurally never bills (self_service, retiro) -> no reason at
      all, regardless of order age or charge presence
  (b) order under 48h old, mode implies billing, no charge -> reason
      `billing_too_recent`, `incompleto` stays False
  (c) order 48h+ old, mode implies billing, no charge -> REASON_BILLING_NOT_SWEPT

All timestamps below are constructed tz-aware, relative to a `NOW` captured
once at import time -- never round-tripped through SQLite before use in an
assertion (the comparison itself reads back through SQLite, but
`breakdown_service` treats a reloaded naive datetime as UTC, mirroring the
repo-wide `tzinfo is None -> assume UTC` pattern).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_ventas_desglose.breakdown_service import (
    REASON_BILLING_NOT_SWEPT,
    REASON_BILLING_TOO_RECENT,
    compute_breakdown,
)

NOW = datetime.now(timezone.utc)


def _order(db, order_id: int, shipping_id=None, date_created=None, has_no_shipping_tag=None) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=NOW,
            date_created=date_created,
            seller_id=999,
            shipping_id=shipping_id,
            has_no_shipping_tag=has_no_shipping_tag,
        )
    )


def _shipment(db, shipment_id: int, logistic_type: str) -> None:
    db.add(MlShipmentOps(shipment_id=shipment_id, logistic_type=logistic_type))


def _payment(db, payment_id: int, order_id: int) -> None:
    db.add(
        MlPaymentOps(
            payment_id=payment_id,
            order_id=order_id,
            status="approved",
            net_received_amount=Decimal("100"),
        )
    )


class TestThreeCaseBillingWarning:
    def test_self_service_never_warns(self, db) -> None:
        order_id = 9500
        _order(db, order_id, shipping_id=9500, date_created=NOW - timedelta(days=30))
        _shipment(db, 9500, "self_service")
        _payment(db, 9500, order_id)
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert REASON_BILLING_NOT_SWEPT not in result.incomplete_reasons
        assert REASON_BILLING_TOO_RECENT not in result.incomplete_reasons
        assert result.incompleto is False

    def test_retiro_never_warns(self, db) -> None:
        """No shipment row exists (has_shipment=False) but the order tags
        `no_shipping` -> mode resolves to `retiro` per PR1's cascade, even
        though `MlOrdersOps.shipping_id` itself is still set."""
        order_id = 9501
        _order(db, order_id, shipping_id=9501, date_created=NOW - timedelta(days=30), has_no_shipping_tag=True)
        _payment(db, 9501, order_id)
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert REASON_BILLING_NOT_SWEPT not in result.incomplete_reasons
        assert REASON_BILLING_TOO_RECENT not in result.incomplete_reasons
        assert result.incompleto is False

    def test_recent_order_billing_too_recent(self, db) -> None:
        order_id = 9502
        _order(db, order_id, shipping_id=9502, date_created=NOW - timedelta(hours=5))
        _shipment(db, 9502, "cross_docking")
        _payment(db, 9502, order_id)
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert REASON_BILLING_TOO_RECENT in result.incomplete_reasons
        assert REASON_BILLING_NOT_SWEPT not in result.incomplete_reasons
        assert result.incompleto is False

    def test_missing_billing_warns_after_48h(self, db) -> None:
        order_id = 9503
        _order(db, order_id, shipping_id=9503, date_created=NOW - timedelta(hours=49))
        _shipment(db, 9503, "cross_docking")
        _payment(db, 9503, order_id)
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert REASON_BILLING_NOT_SWEPT in result.incomplete_reasons
        assert REASON_BILLING_TOO_RECENT not in result.incomplete_reasons
        assert result.incompleto is True
