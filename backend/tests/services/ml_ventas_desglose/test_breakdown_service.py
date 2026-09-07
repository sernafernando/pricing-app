"""RED/GREEN -- `compute_breakdown` (ml-ventas-desglose-costos, corte 6).

Every scenario below mirrors a real, measured case (see obs #1960, #1965,
#1966), not a synthetic one:

  REQ-1 -- net of a sale is the SUM of `net_received_amount` over its
           `approved` payments, never a single payment's value (order
           2000018322969636: two approved payments split the total AND the
           shipping amount).
  REQ-2 -- a fully-returned sale nets to ZERO even though the payment's
           `net_received_amount` is reported positive (order
           2000018325540962).
  REQ-3 -- `rejected`/`cancelled` payments never contribute net or charges.
  REQ-4 -- the seller-vs-buyer/coupon predicate: `coupon`, `bonus`,
           `financing_fee` (buyer-paid) and any `payer`-named charge are
           excluded; `financing_add_on_fee` (seller-paid) is NOT excluded.
  REQ-5 -- `flat_fee` sums once PER ORDER in a pack (pack 2000014907031737:
           1330 charged on each of two payments).
  REQ-6 -- "Envios" never reads `MlShipmentOps.sender_cost`; it is built
           from `shp_*` payment charges plus billing bridge charges whose
           `detail_sub_type` is CXD/CFF/CSSTEC, deduped by `detail_id` so a
           pack's shared shipping charge is not double counted.
  REQ-7 -- missing data marks `incompleto=True` with a reason; the service
           never fabricates a number to fill the gap.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models.ml_billing import MlBillingCharge, MlBillingChargeOrder
from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.services.ml_ventas_desglose.breakdown_service import (
    REASON_BILLING_NOT_SWEPT,
    REASON_PAYMENTS_NOT_SYNCED,
    REASON_SHIPMENT_COSTS_MISSING,
    compute_breakdown,
)


def _order(db, order_id: int, pack_id=None, shipping_id=None) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            seller_id=999,
            shipping_id=shipping_id,
        )
    )


def _payment(
    db,
    payment_id: int,
    order_id: int,
    status: str = "approved",
    net_received_amount=None,
    transaction_amount_refunded=None,
    shipping_amount=None,
) -> None:
    db.add(
        MlPaymentOps(
            payment_id=payment_id,
            order_id=order_id,
            status=status,
            net_received_amount=net_received_amount,
            transaction_amount_refunded=transaction_amount_refunded,
            shipping_amount=shipping_amount,
        )
    )


def _charge(db, payment_id: int, name: str, type_: str, amount, refunded=None) -> None:
    db.add(
        MlPaymentCharge(
            payment_id=payment_id,
            name=name,
            type=type_,
            amount=amount,
            refunded=refunded,
        )
    )


class TestNetIsSummedAcrossApprovedPayments:
    def test_two_approved_payments_split_total_and_shipping(self, db) -> None:
        """Order 2000018322969636 -- REQ-1."""
        order_id = 2000018322969636
        _order(db, order_id)
        _payment(db, 1, order_id, status="approved", net_received_amount=Decimal("7371.11"))
        _payment(
            db, 2, order_id, status="approved", net_received_amount=Decimal("12528.89"), shipping_amount=Decimal("1500")
        )
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.neto == Decimal("19900.00")
        assert result.incompleto is False

    def test_single_payment_order_nets_that_payment_alone(self, db) -> None:
        order_id = 111
        _order(db, order_id)
        _payment(db, 10, order_id, status="approved", net_received_amount=Decimal("500.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.neto == Decimal("500.00")


class TestReturnedSaleNetsToZero:
    def test_fully_refunded_payment_nets_zero_despite_positive_net_received(self, db) -> None:
        """Order 2000018325540962 -- REQ-2. The identity verified 20/20:
        transaction_amount_refunded - sum(refunded seller charges) ==
        net_received_amount, so subtracting it back out zeroes the net."""
        order_id = 2000018325540962
        _order(db, order_id)
        # net_received_amount stays POSITIVE even though everything was
        # returned -- the raw payment field lies about the outcome.
        _payment(
            db,
            20,
            order_id,
            status="refunded",
            net_received_amount=Decimal("27614.00"),
            transaction_amount_refunded=Decimal("29000.00"),
        )
        _charge(db, 20, "meli_percentage_fee", "fee", Decimal("1386.00"), refunded=Decimal("1386.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.neto == Decimal("0.00")

    def test_rejected_payment_is_excluded_entirely_despite_loaded_charges(self, db) -> None:
        """REQ-3 -- a rejected payment has net=0 WITH charges loaded;
        summing it would fabricate a cost for a sale that never happened."""
        order_id = 222
        _order(db, order_id)
        _payment(db, 30, order_id, status="rejected", net_received_amount=Decimal("0"))
        _charge(db, 30, "meli_percentage_fee", "fee", Decimal("500.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.neto == Decimal("0.00")
        assert result.lines == []


class TestSellerVsBuyerPredicate:
    def test_coupon_and_bonus_charges_are_excluded_from_lines(self, db) -> None:
        order_id = 300
        _order(db, order_id)
        _payment(db, 40, order_id, status="approved", net_received_amount=Decimal("100"))
        _charge(db, 40, "coupon", "coupon", Decimal("50.00"))
        _charge(db, 40, "some_bonus", "bonus", Decimal("20.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.lines == []

    def test_charge_type_bonus_excludes_it_even_with_a_mapped_line_name(self, db) -> None:
        """The `type` check must fire independently of `name` -- a charge
        named like a real line but typed `bonus`/`coupon` is still not the
        seller's."""
        order_id = 304
        _order(db, order_id)
        _payment(db, 44, order_id, status="approved", net_received_amount=Decimal("100"))
        _charge(db, 44, "meli_percentage_fee", "bonus", Decimal("999.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.lines == []

    def test_buyer_financing_fee_excluded_but_seller_financing_add_on_fee_kept(self, db) -> None:
        """`financing_fee` (buyer pays) vs `financing_add_on_fee` (we pay
        ML) -- opposite pockets despite the similar name."""
        order_id = 301
        _order(db, order_id)
        _payment(db, 41, order_id, status="approved", net_received_amount=Decimal("100"))
        _charge(db, 41, "financing_fee", "fee", Decimal("30.00"))
        _charge(db, 41, "financing_add_on_fee", "fee", Decimal("15.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        labels = {line.concepto: line.monto for line in result.lines}
        assert "Costo por ofrecer cuotas" in labels
        assert labels["Costo por ofrecer cuotas"] == Decimal("15.00")
        assert len(result.lines) == 1

    def test_payer_named_charge_excluded(self, db) -> None:
        order_id = 302
        _order(db, order_id)
        _payment(db, 42, order_id, status="approved", net_received_amount=Decimal("100"))
        _charge(db, 42, "IVA_ADD_percentage_payer", "tax", Decimal("21.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.lines == []

    def test_seller_tax_charges_collapse_into_one_impuestos_line(self, db) -> None:
        order_id = 303
        _order(db, order_id)
        _payment(db, 43, order_id, status="approved", net_received_amount=Decimal("100"))
        _charge(db, 43, "IVA_percentage_seller", "tax", Decimal("10.00"))
        _charge(db, 43, "IIBB_percentage_seller", "tax", Decimal("5.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        labels = {line.concepto: line.monto for line in result.lines}
        assert labels["Impuestos"] == Decimal("15.00")
        assert len(result.lines) == 1


class TestFlatFeePerOrderInAPack:
    def test_flat_fee_summed_once_per_order_in_a_pack(self, db) -> None:
        """Pack 2000014907031737 -- REQ-5: 1330 charged on EACH of the
        pack's two payments (one per order), and both must count."""
        pack_id = 2000014907031737
        order_a, order_b = 5001, 5002
        _order(db, order_a, pack_id=pack_id)
        _order(db, order_b, pack_id=pack_id)
        _payment(db, 50, order_a, status="approved", net_received_amount=Decimal("1000"))
        _payment(db, 51, order_b, status="approved", net_received_amount=Decimal("1000"))
        _charge(db, 50, "flat_fee", "fee", Decimal("1330.00"))
        _charge(db, 51, "flat_fee", "fee", Decimal("1330.00"))
        db.commit()

        result = compute_breakdown(db, [order_a, order_b])

        labels = {line.concepto: line.monto for line in result.lines}
        assert labels["Costo fijo"] == Decimal("2660.00")


class TestShippingLine:
    def test_shipping_never_reads_sender_cost_and_is_zero_for_self_service(self, db) -> None:
        """REQ-6 -- verified live: 121/125 orders with sender_cost > 0 are
        self_service, and ML never charges anything for those."""
        order_id = 600
        _order(db, order_id, shipping_id=None)
        _payment(db, 60, order_id, status="approved", net_received_amount=Decimal("100"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert not any(line.concepto == "Envios" for line in result.lines)

    def test_shp_charge_builds_the_envios_line(self, db) -> None:
        order_id = 601
        _order(db, order_id, shipping_id=777)
        _payment(db, 61, order_id, status="approved", net_received_amount=Decimal("100"))
        _charge(db, 61, "shp_hub_lm_out", "shipping", Decimal("450.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        labels = {line.concepto: line.monto for line in result.lines}
        assert labels["Envios"] == Decimal("450.00")
        assert result.incompleto is False

    def test_pack_shipping_billing_charge_deduped_by_detail_id(self, db) -> None:
        """A pack's shipping charge is bridged to every order in the pack
        but must be counted ONCE, not once per order."""
        pack_id = 700
        order_a, order_b = 7001, 7002
        _order(db, order_a, pack_id=pack_id, shipping_id=900)
        _order(db, order_b, pack_id=pack_id, shipping_id=900)
        _payment(db, 70, order_a, status="approved", net_received_amount=Decimal("100"))
        _payment(db, 71, order_b, status="approved", net_received_amount=Decimal("100"))

        db.add(MlBillingCharge(detail_id="D-shared", detail_sub_type="CXD", amount=Decimal("300.00")))
        db.add(MlBillingChargeOrder(detail_id="D-shared", order_id=order_a))
        db.add(MlBillingChargeOrder(detail_id="D-shared", order_id=order_b))
        db.commit()

        result = compute_breakdown(db, [order_a, order_b])

        labels = {line.concepto: line.monto for line in result.lines}
        assert labels["Envios"] == Decimal("300.00")


class TestIncompleteReasons:
    def test_no_payments_marks_payments_not_synced(self, db) -> None:
        order_id = 800
        _order(db, order_id)
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.incompleto is True
        assert REASON_PAYMENTS_NOT_SYNCED in result.incomplete_reasons
        assert result.neto is None

    def test_shipment_without_any_shipping_charge_or_billing_link_is_billing_not_swept(self, db) -> None:
        order_id = 801
        _order(db, order_id, shipping_id=901)
        _payment(db, 80, order_id, status="approved", net_received_amount=Decimal("100"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.incompleto is True
        assert REASON_BILLING_NOT_SWEPT in result.incomplete_reasons

    def test_self_service_shipment_with_no_shipping_charge_but_ordinary_billing_is_complete(self, db) -> None:
        """The regression this section exists to pin: a `self_service`
        order has a shipment, ZERO shipping charge (correctly -- the
        seller pays its own carrier, ML never bills it), and ordinary
        billing rows (a CVFV "Cargo por vender", not a shipping subtype).
        Measured 121/125 (obs #1965): this is the NORMAL case, not a
        missing-data signal, and must never be marked incompleto."""
        order_id = 802
        _order(db, order_id, shipping_id=902)
        _payment(db, 81, order_id, status="approved", net_received_amount=Decimal("100"))
        db.add(MlBillingCharge(detail_id="D-other", detail_sub_type="CVFV", amount=Decimal("10.00")))
        db.add(MlBillingChargeOrder(detail_id="D-other", order_id=order_id))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.incompleto is False
        assert not any(line.concepto == "Envios" for line in result.lines)

    def test_shipment_costs_missing_reason_is_never_emitted(self, db) -> None:
        """`REASON_SHIPMENT_COSTS_MISSING` stays defined for contract
        stability but must never actually be raised -- see module
        docstring."""
        order_id = 803
        _order(db, order_id, shipping_id=903)
        _payment(db, 82, order_id, status="approved", net_received_amount=Decimal("100"))
        db.add(MlBillingCharge(detail_id="D-other-2", detail_sub_type="CVFV", amount=Decimal("10.00")))
        db.add(MlBillingChargeOrder(detail_id="D-other-2", order_id=order_id))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert REASON_SHIPMENT_COSTS_MISSING not in result.incomplete_reasons

    def test_no_order_ids_returns_incomplete_with_no_data(self, db) -> None:
        result = compute_breakdown(db, [])

        assert result.incompleto is True
        assert result.neto is None
        assert result.lines == []
