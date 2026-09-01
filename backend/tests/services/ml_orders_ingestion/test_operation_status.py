"""RED/GREEN -- `app.services.ml_orders_ingestion.operation_status`
(ml-ventas-listado).

One test per precedence-table row (spec instruction: "the precedence
table deserves a test per row, including `unknown`"), plus the goods-axis
mapping and its own `unknown` fallback.
"""

from __future__ import annotations

from app.services.ml_orders_ingestion.operation_status import (
    goods_status_of,
    operation_status_of,
)


class TestOperationStatusPrecedence:
    def test_cancelled_covered_by_marketplace(self):
        assert (
            operation_status_of(
                order_status="cancelled",
                payment_status="approved",
                claim_status="opened",
                covered_by_marketplace=True,
                shipping_status="delivered",
            )
            == "cancelled_ml_covered"
        )

    def test_cancelled_not_covered(self):
        assert (
            operation_status_of(
                order_status="cancelled",
                payment_status="approved",
                claim_status=None,
                covered_by_marketplace=False,
                shipping_status=None,
            )
            == "cancelled"
        )

    def test_cancelled_covered_none_treated_as_plain_cancelled(self):
        """`covered_by_marketplace=None` (the only value this ingestion
        slice ever actually writes, see `mapper.py`) must NOT be treated
        as covered -- only an explicit `True` reaches `cancelled_ml_covered`."""
        assert (
            operation_status_of(
                order_status="cancelled",
                payment_status="approved",
                covered_by_marketplace=None,
            )
            == "cancelled"
        )

    def test_payment_in_mediation_is_in_dispute_even_when_paid_status(self):
        assert (
            operation_status_of(
                order_status="paid",
                payment_status="in_mediation",
                claim_status=None,
                shipping_status="delivered",
            )
            == "in_dispute"
        )

    def test_open_claim_of_any_stage_is_in_dispute(self):
        """2026-09-01 amendment: an open claim of ANY stage counts, not
        only `in_mediation` payment status."""
        assert (
            operation_status_of(
                order_status="paid",
                payment_status="approved",
                claim_status="opened",
                shipping_status="delivered",
            )
            == "in_dispute"
        )

    def test_closed_claim_does_not_force_in_dispute(self):
        assert (
            operation_status_of(
                order_status="paid",
                payment_status="approved",
                claim_status="closed",
                shipping_status="delivered",
            )
            == "delivered"
        )

    def test_delivered_when_shipping_delivered_and_no_open_claim(self):
        assert (
            operation_status_of(
                order_status="paid",
                payment_status="approved",
                claim_status=None,
                shipping_status="delivered",
            )
            == "delivered"
        )

    def test_paid_when_not_delivered_and_no_open_claim(self):
        assert (
            operation_status_of(
                order_status="paid",
                payment_status="approved",
                claim_status=None,
                shipping_status="shipped",
            )
            == "paid"
        )

    def test_confirmed_order_status_counts_as_paid(self):
        assert (
            operation_status_of(
                order_status="confirmed",
                payment_status="approved",
                shipping_status="ready_to_ship",
            )
            == "paid"
        )

    def test_unknown_when_nothing_matches(self):
        assert (
            operation_status_of(
                order_status="invalid",
                payment_status=None,
                claim_status=None,
                shipping_status=None,
            )
            == "unknown"
        )

    def test_unknown_for_all_none_input(self):
        assert operation_status_of(order_status=None, payment_status=None) == "unknown"


class TestGoodsStatus:
    def test_ready_to_ship_is_in_warehouse(self):
        assert goods_status_of("ready_to_ship") == "in_warehouse"

    def test_handling_is_in_warehouse(self):
        assert goods_status_of("handling") == "in_warehouse"

    def test_shipped_is_in_transit(self):
        assert goods_status_of("shipped") == "in_transit"

    def test_delivered_is_delivered(self):
        assert goods_status_of("delivered") == "delivered"

    def test_not_delivered_is_returned_undelivered(self):
        assert goods_status_of("not_delivered") == "returned_undelivered"

    def test_none_is_unknown(self):
        assert goods_status_of(None) == "unknown"

    def test_unrecognised_status_is_unknown(self):
        assert goods_status_of("some_future_ml_status") == "unknown"
