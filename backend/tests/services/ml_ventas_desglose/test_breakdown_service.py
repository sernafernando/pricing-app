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

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.codigo_postal_cordon import CodigoPostalCordon
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.logistica_costo_cordon import LogisticaCostoCordon
from app.models.transporte import Transporte
from app.models.ml_billing import MlBillingCharge, MlBillingChargeOrder
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.services.ml_ventas_desglose.breakdown_service import (
    CONCEPTO_ENVIOS,
    REASON_BILLING_NOT_SWEPT,
    REASON_FLEX_COST_UNKNOWN,
    REASON_ITEM_LINES_ITEM_SIN_CANTIDAD,
    REASON_ITEM_LINES_ITEM_SIN_PRECIO,
    REASON_ITEM_LINES_NO_ITEMS,
    REASON_ITEM_LINES_ORDEN_SIN_ITEMS,
    compute_neto_by_order_ids,
    compute_neto_desglose_by_order_ids,
    REASON_PAYMENTS_NOT_COUNTABLE,
    REASON_PAYMENTS_NOT_SYNCED,
    compute_breakdown,
)


def _item(db, order_id, item_id, title="Board Asus", quantity=1, unit_price=None, seller_sku="SKU-1") -> None:
    db.add(
        MlOrderItemOps(
            order_id=order_id,
            item_id=item_id,
            title=title,
            quantity=quantity,
            unit_price=unit_price,
            seller_sku=seller_sku,
        )
    )


def _order(db, order_id: int, pack_id=None, shipping_id=None, paid_amount=None) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            seller_id=999,
            shipping_id=shipping_id,
            paid_amount=paid_amount,
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
        summing it would fabricate a cost for a sale that never happened.

        The net is None, not zero. A rejected payment does not say the
        sale left nothing -- it says THAT collection did not go through.
        Zero is what a fully refunded sale reports, and claiming it here
        would show a sale as returned when all we know is that one payment
        failed and no other has synced.
        """
        order_id = 222
        _order(db, order_id)
        _payment(db, 30, order_id, status="rejected", net_received_amount=Decimal("0"))
        _charge(db, 30, "meli_percentage_fee", "fee", Decimal("500.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.neto is None
        assert result.lines == []
        # A null net with no badge is a silent blank: the panel has a
        # channel for "we do not know" and has to use it.
        assert result.incompleto is True
        # NOT `payments_not_synced`: the payment IS here, with its charges.
        # Telling the operator to wait for a sweep that already ran sends
        # them to look in the wrong place.
        assert REASON_PAYMENTS_NOT_COUNTABLE in result.incomplete_reasons
        assert REASON_PAYMENTS_NOT_SYNCED not in result.incomplete_reasons


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

    def test_tax_names_ml_does_not_use_fall_back_to_one_impuestos_line(self, db) -> None:
        """These two names are NOT shapes ML sends -- production has 35
        distinct tax names and every one starts with `tax_withholding`.
        They are here on purpose, as the unknown-name case: an unfamiliar
        tax still has to appear as money the seller paid."""
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

    def test_real_tax_names_become_one_line_each_naming_tax_and_province(self, db) -> None:
        """The names below are recorded from production. Collapsing them
        into a single "Impuestos" number tells the operator nothing: a
        SIRTAC withholding, its provincial surcharge and the national
        debit/credit tax are three different charges."""
        order_id = 304
        _order(db, order_id)
        _payment(db, 44, order_id, status="approved", net_received_amount=Decimal("100"))
        _charge(db, 44, "tax_withholding_sirtac-jujuy", "tax", Decimal("10.00"))
        _charge(db, 44, "tax_withholding_sirtac_sobretasa-jujuy", "tax", Decimal("25.00"))
        _charge(db, 44, "tax_withholding_collector-debitos_creditos", "tax", Decimal("7.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        labels = {line.concepto: line.monto for line in result.lines}
        assert labels["Retención IIBB (Jujuy) · SIRTAC"] == Decimal("10.00")
        assert labels["Retención IIBB por falta de alta (Jujuy)"] == Decimal("25.00")
        assert labels["Impuesto a los débitos y créditos"] == Decimal("7.00")
        assert "Impuestos" not in labels

    def test_splitting_the_taxes_does_not_change_what_they_add_up_to(self, db) -> None:
        """The point of this change is LABELLING. If naming the lines
        moved the money, the breakdown would stop reconciling with the
        net -- which is the one thing it exists to do."""
        order_id = 305
        _order(db, order_id)
        _payment(db, 45, order_id, status="approved", net_received_amount=Decimal("100"))
        _charge(db, 45, "tax_withholding_sirtac-salta", "tax", Decimal("3.50"))
        _charge(db, 45, "tax_withholding_sirtac-catamarca", "tax", Decimal("6.25"))
        _charge(db, 45, "tax_withholding_nunca_visto-marte", "tax", Decimal("0.25"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        tax_lines = [line for line in result.lines if "Retenci" in line.concepto or line.concepto == "Impuestos"]
        assert sum(line.monto for line in tax_lines) == Decimal("10.00")

    def test_two_provinces_do_not_get_merged_into_one_line(self, db) -> None:
        """Same tax, different province, is two rows on ML's own side and
        has to stay two rows here -- merging them hides where the money
        went."""
        order_id = 306
        _order(db, order_id)
        _payment(db, 46, order_id, status="approved", net_received_amount=Decimal("100"))
        _charge(db, 46, "tax_withholding_sirtac-salta", "tax", Decimal("3.00"))
        _charge(db, 46, "tax_withholding_sirtac-jujuy", "tax", Decimal("4.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        labels = {line.concepto: line.monto for line in result.lines}
        assert labels["Retención IIBB (Salta) · SIRTAC"] == Decimal("3.00")
        assert labels["Retención IIBB (Jujuy) · SIRTAC"] == Decimal("4.00")


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
        # No payment rows at all: the sweep genuinely owes us data, so
        # "not synced yet" is the honest reason here.
        assert REASON_PAYMENTS_NOT_SYNCED in result.incomplete_reasons
        assert REASON_PAYMENTS_NOT_COUNTABLE not in result.incomplete_reasons
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
        missing-data signal, and must never be marked incompleto.

        The shipment row's `logistic_type="self_service"` is what now
        drives the "never warns" mode -- ml-ventas-modo-logistico PR2."""
        order_id = 802
        _order(db, order_id, shipping_id=902)
        db.add(MlShipmentOps(shipment_id=902, logistic_type="self_service"))
        _payment(db, 81, order_id, status="approved", net_received_amount=Decimal("100"))
        db.add(MlBillingCharge(detail_id="D-other", detail_sub_type="CVFV", amount=Decimal("10.00")))
        db.add(MlBillingChargeOrder(detail_id="D-other", order_id=order_id))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.incompleto is False
        assert not any(line.concepto == "Envios" for line in result.lines)

    def test_no_order_ids_returns_incomplete_with_no_data(self, db) -> None:
        result = compute_breakdown(db, [])

        assert result.incompleto is True
        assert result.neto is None
        assert result.lines == []


class TestTheTwoPathsToTheNetAgree:
    """The listing and the panel compute the same money by different code.

    `compute_neto_by_order_ids` resolves a whole page in two bulk queries;
    `compute_breakdown` resolves one sale at a time. They share the
    predicates -- `is_seller_charge`, `payment_effective_net`,
    `RELEVANT_PAYMENT_STATUSES` -- but they are separate loops, and
    nothing forced them to agree until this test.

    They must, because a sale showing one net in the listing and another
    inside its own panel is the worst failure available on that screen:
    both look authoritative and the operator cannot tell which lies.
    """

    def _assert_agree(self, db, order_ids):
        """Compares None to None, never folding it into a zero.

        The first version summed with `if v is not None`, turning "we do
        not know" into 0 BEFORE comparing -- so the two paths could
        disagree in exactly the way this class exists to catch while the
        helper reported agreement.
        """
        por_orden = compute_neto_by_order_ids(db, order_ids)
        valores = [por_orden[o] for o in order_ids]
        listado = None if all(v is None for v in valores) else sum(v for v in valores if v is not None)
        panel = compute_breakdown(db, order_ids)
        assert panel.neto == listado, f"listing says {listado}, panel says {panel.neto} for {order_ids}"
        return panel.neto

    def test_a_plain_approved_sale(self, db) -> None:
        _order(db, 1)
        _payment(db, 10, 1, net_received_amount=Decimal("87.50"))
        _charge(db, 10, "meli_percentage_fee", "fee", Decimal("12.50"))
        db.commit()
        assert self._assert_agree(db, [1]) == Decimal("87.50")

    def test_two_approved_payments_splitting_one_order(self, db) -> None:
        # Order 2000018322969636: two approved payments split the total.
        _order(db, 2000018322969636)
        _payment(db, 11, 2000018322969636, net_received_amount=Decimal("7371.11"))
        _payment(db, 12, 2000018322969636, net_received_amount=Decimal("12528.89"))
        db.commit()
        assert self._assert_agree(db, [2000018322969636]) == Decimal("19900.00")

    def test_a_fully_refunded_sale(self, db) -> None:
        # The reported net stays positive; both paths must still say zero.
        _order(db, 3)
        _payment(
            db,
            13,
            3,
            status="refunded",
            net_received_amount=Decimal("27614"),
            transaction_amount_refunded=Decimal("47000"),
        )
        _charge(db, 13, "meli_percentage_fee", "fee", Decimal("7285"), refunded=Decimal("7285"))
        _charge(db, 13, "tax_withholding_sirtac-catamarca", "tax", Decimal("141"), refunded=Decimal("141"))
        _charge(db, 13, "shp_cross_docking", "shipping", Decimal("6790"), refunded=Decimal("6790"))
        _charge(db, 13, "tax_withholding_collector-debitos_creditos", "tax", Decimal("282"), refunded=Decimal("282"))
        _charge(
            db,
            13,
            "tax_withholding_sirtac_sobretasa-catamarca",
            "tax",
            Decimal("705"),
            refunded=Decimal("705"),
        )
        _charge(db, 13, "financing_add_on_fee", "fee", Decimal("4183"), refunded=Decimal("4183"))
        db.commit()
        assert self._assert_agree(db, [3]) == Decimal("0")

    def test_a_rejected_payment_alongside_an_approved_one(self, db) -> None:
        # The rejected one carries a NON-ZERO net on purpose. With zero,
        # counting it or not made no difference and the test passed while
        # the listing summed rejected payments -- verified by mutation.
        _order(db, 4)
        _payment(db, 14, 4, status="rejected", net_received_amount=Decimal("999"))
        _payment(db, 15, 4, net_received_amount=Decimal("500"))
        db.commit()
        assert self._assert_agree(db, [4]) == Decimal("500")

    def test_buyer_charges_that_must_not_move_the_net(self, db) -> None:
        _order(db, 5)
        _payment(
            db,
            16,
            5,
            net_received_amount=Decimal("940"),
            transaction_amount_refunded=Decimal("100"),
        )
        _charge(db, 16, "meli_percentage_fee", "fee", Decimal("60"), refunded=Decimal("60"))
        # The buyer's, all four exclusions represented.
        _charge(db, 16, "coupon_rebate", "coupon", Decimal("30"), refunded=Decimal("30"))
        _charge(db, 16, "financing", "bonus", Decimal("10"), refunded=Decimal("10"))
        _charge(db, 16, "financing_fee", "fee", Decimal("20"), refunded=Decimal("20"))
        _charge(db, 16, "tax_withholding_payer-debitos_creditos", "tax", Decimal("5"), refunded=Decimal("5"))
        db.commit()
        self._assert_agree(db, [5])

    def test_a_pack_of_three_orders(self, db) -> None:
        for oid, pid, net in ((6, 17, "4856.66"), (7, 18, "7764.13"), (8, 19, "29177.60")):
            _order(db, oid, pack_id=777)
            _payment(db, pid, oid, net_received_amount=Decimal(net))
        db.commit()
        assert self._assert_agree(db, [6, 7, 8]) == Decimal("41798.39")

    def test_an_order_with_no_synced_payments_at_all(self, db) -> None:
        # None on the listing side, and the panel reports no neto either --
        # neither may turn it into a zero, which would read as a return.
        _order(db, 9)
        db.commit()
        assert compute_neto_by_order_ids(db, [9])[9] is None
        assert compute_breakdown(db, [9]).neto is None

    def test_a_sale_in_mediation_is_money_collected_not_money_lost(self, db) -> None:
        """Order 2000018092595428, measured live: `in_mediation`, no refund,
        199.707,50 collected. While that status was missing from the
        relevant set it read as ZERO -- indistinguishable from a sale that
        was returned in full. 36 of the 117 payments behind our claims are
        in this state.
        """
        _order(db, 2000018092595428)
        _payment(db, 20, 2000018092595428, status="in_mediation", net_received_amount=Decimal("199707.50"))
        db.commit()
        assert self._assert_agree(db, [2000018092595428]) == Decimal("199707.50")

    def test_an_unrecognised_status_reports_unknown_not_zero(self, db) -> None:
        """Whatever ML adds next must not arrive as a confident zero.

        Zero is a measured answer -- it is what a refunded sale reports.
        A status we do not model yet is an absence, and it has to look
        like one, the same as a sale still waiting on the sweep.
        """
        _order(db, 21)
        _payment(db, 22, 21, status="un_estado_que_todavia_no_existe", net_received_amount=Decimal("1234"))
        db.commit()
        # Both paths, not only the bulk one: the guard went into the
        # listing alone and the panel kept answering zero for this sale.
        assert self._assert_agree(db, [21]) is None
        assert compute_neto_by_order_ids(db, [21])[21] is None
        # And the panel says WHY it has no number, instead of rendering
        # an unexplained blank.
        panel = compute_breakdown(db, [21])
        assert panel.incompleto is True
        assert REASON_PAYMENTS_NOT_COUNTABLE in panel.incomplete_reasons

    def test_a_partial_refund_larger_than_the_transaction(self, db) -> None:
        """Order 4430760076, measured live: refunded 3.691,49 against a
        transaction of 3.490 -- more given back than the sale itself, and
        the formula still lands on exactly zero without a special case.

        Its charge also arrives with `type: None` (older data), which the
        predicate has to tolerate rather than crash on.
        """
        _order(db, 4430760076)
        _payment(
            db,
            23,
            4430760076,
            status="refunded",
            net_received_amount=Decimal("3215.79"),
            transaction_amount_refunded=Decimal("3691.49"),
        )
        _charge(db, 23, "meli_fee", None, Decimal("475.70"), refunded=Decimal("475.70"))
        db.commit()
        assert self._assert_agree(db, [4430760076]) == Decimal("0.00")

    def test_a_sale_with_sirtac_add_back(self, db) -> None:
        """ml-ventas-neto-iibb-varios R1: both paths must add back the
        non-refunded SIRTAC withholding identically."""
        _order(db, 24)
        _payment(db, 24, 24, net_received_amount=Decimal("800.00"))
        _charge(db, 24, "tax_withholding_sirtac-caba", "tax", Decimal("300.00"))
        db.commit()
        assert self._assert_agree(db, [24]) == Decimal("1100.00")

    def test_a_sale_with_partially_refunded_sirtac(self, db) -> None:
        _order(db, 25)
        _payment(db, 25, 25, net_received_amount=Decimal("800.00"))
        _charge(db, 25, "tax_withholding_sirtac-caba", "tax", Decimal("300.00"), refunded=Decimal("100.00"))
        db.commit()
        assert self._assert_agree(db, [25]) == Decimal("1000.00")  # 800 + (300-100)


class TestRecoverableLineOrigen:
    """ml-ventas-neto-iibb-varios D2: a SIRTAC line's `origen` is
    `"recuperable"` (shown, not subtracted from `neto`); every other line
    stays `"api"`. `neto_depositado`/`retenciones_recuperables` mirror the
    worked example."""

    def test_sirtac_line_is_recuperable_others_stay_api(self, db) -> None:
        order_id = 2000018567320906
        payment_id = 180131165380
        _item(db, order_id, "MLA2060835678", unit_price=Decimal("597408.67"))
        _order(db, order_id)
        _payment(db, payment_id, order_id, net_received_amount=Decimal("502165.91"))
        _charge(db, payment_id, "meli_percentage_fee", "fee", Decimal("74676.08"))
        _charge(db, payment_id, "shp_cross_docking", "shipping", Decimal("15190.00"))
        _charge(db, payment_id, "tax_withholding_collector-debitos_creditos", "tax", Decimal("3584.45"))
        _charge(db, payment_id, "tax_withholding_sirtac-caba", "tax", Decimal("1792.23"))
        db.commit()

        panel = compute_breakdown(db, [order_id])

        assert panel.neto == Decimal("503958.14")
        assert panel.neto_depositado == Decimal("502165.91")
        assert panel.retenciones_recuperables == Decimal("1792.23")

        by_concepto = {line.concepto: line.origen for line in panel.lines}
        recuperables = [c for c, origen in by_concepto.items() if origen == "recuperable"]
        assert len(recuperables) == 1
        assert "SIRTAC" in recuperables[0]
        for concepto, origen in by_concepto.items():
            if concepto not in recuperables:
                assert origen == "api"

    def test_no_sirtac_defaults_neto_depositado_to_neto(self, db) -> None:
        _order(db, 26)
        _payment(db, 26, 26, net_received_amount=Decimal("500.00"))
        db.commit()

        panel = compute_breakdown(db, [26])

        assert panel.retenciones_recuperables == Decimal("0")
        assert panel.neto_depositado == Decimal("500.00")

    def test_no_relevant_payments_neto_depositado_is_none(self, db) -> None:
        _order(db, 27)
        db.commit()

        panel = compute_breakdown(db, [27])

        assert panel.neto is None
        assert panel.neto_depositado is None


class TestBulkNetoDesglose:
    """ml-ventas-neto-iibb-varios PR1.T12: the listing needs
    `neto_depositado`/`retenciones_recuperables` per order in bulk (two
    queries, same shape as `compute_neto_by_order_ids`), never one query
    per row."""

    def test_bulk_matches_compute_breakdown_worked_example(self, db) -> None:
        order_id = 2000018567320906
        payment_id = 180131165380
        _item(db, order_id, "MLA2060835678", unit_price=Decimal("597408.67"))
        _order(db, order_id)
        _payment(db, payment_id, order_id, net_received_amount=Decimal("502165.91"))
        _charge(db, payment_id, "meli_percentage_fee", "fee", Decimal("74676.08"))
        _charge(db, payment_id, "tax_withholding_sirtac-caba", "tax", Decimal("1792.23"))
        db.commit()

        result = compute_neto_desglose_by_order_ids(db, [order_id])[order_id]

        assert result == (Decimal("502165.91"), Decimal("1792.23"))

    def test_no_sirtac_is_zero_not_none(self, db) -> None:
        _order(db, 28)
        _payment(db, 28, 28, net_received_amount=Decimal("500.00"))
        db.commit()

        result = compute_neto_desglose_by_order_ids(db, [28])[28]

        assert result == (Decimal("500.00"), Decimal("0"))

    def test_no_relevant_payments_is_none_none(self, db) -> None:
        _order(db, 29)
        db.commit()

        result = compute_neto_desglose_by_order_ids(db, [29])[29]

        assert result == (None, None)


class TestPerModeShippingSplit:
    """ml-ventas-modo-logistico PR2, task 2.2/2.6 -- the single `Envios`
    line splits by known `shp_*` charge type, with an unrecognised type
    bucketed rather than dropped."""

    def test_known_shp_types_split_correctly(self, db) -> None:
        order_id = 900
        _order(db, order_id, shipping_id=None)
        _payment(db, 90, order_id, status="approved", net_received_amount=Decimal("100"))
        _charge(db, 90, "shp_cross_docking", "shipping", Decimal("300.00"))
        _charge(db, 90, "shp_fulfillment", "shipping", Decimal("150.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        labels = {line.concepto: line.monto for line in result.lines}
        assert labels["Envíos (Colecta)"] == Decimal("300.00")
        assert labels["Envíos (Full)"] == Decimal("150.00")
        envio_total = sum(monto for concepto, monto in labels.items() if concepto.startswith("Env"))
        assert envio_total == Decimal("450.00")

    def test_unrecognized_shp_bucketed_not_dropped(self, db) -> None:
        order_id = 901
        _order(db, order_id, shipping_id=None)
        _payment(db, 91, order_id, status="approved", net_received_amount=Decimal("100"))
        _charge(db, 91, "shp_never_seen_before", "shipping", Decimal("222.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        labels = {line.concepto: line.monto for line in result.lines}
        assert labels[CONCEPTO_ENVIOS] == Decimal("222.00")


class TestFlexRealCost:
    """ml-ventas-modo-logistico PR2, task 2.4/2.7 -- the `propio` Flex
    freight line, never a `$0` line when any input fails to resolve."""

    def _self_service_shipment(self, db, shipment_id: int) -> None:
        db.add(MlShipmentOps(shipment_id=shipment_id, logistic_type="self_service"))

    def _logistica(self, db, logistica_id: int = 1, nombre: str = "Andreani") -> None:
        db.add(Logistica(id=logistica_id, nombre=nombre))

    def test_flex_cost_override_wins(self, db) -> None:
        order_id = 950
        _order(db, order_id, shipping_id=950)
        self._self_service_shipment(db, 950)
        _payment(db, 95, order_id, status="approved", net_received_amount=Decimal("100"))
        self._logistica(db)
        db.add(
            EtiquetaEnvio(
                shipping_id="950",
                fecha_envio=date(2026, 8, 1),
                logistica_id=1,
                costo_override=Decimal("777.00"),
            )
        )
        db.commit()

        result = compute_breakdown(db, [order_id])

        propio_lines = [line for line in result.lines if line.origen == "propio"]
        assert len(propio_lines) == 1
        assert propio_lines[0].monto == Decimal("777.00")
        assert REASON_FLEX_COST_UNKNOWN not in result.incomplete_reasons

    def test_tariff_matches_across_the_accent_the_two_tables_disagree_on(self, db) -> None:
        """THE REAL SHAPE OF THE DATA, not a convenient one. `cp_cordones`
        stores `"Cordón 1"` with the accent; `logistica_costo_cordon` stores
        `"Cordon 1"` without it. The original fixture wrote the SAME string
        into both tables, so the join looked fine while production would
        have matched nothing -- every Flex sale without an override falling
        to `flex_cost_unknown`, wearing the face of honest missing data.

        Same lesson as the `date_last_updated` week: a fixture is a guess
        about the data's shape, and a guess that agrees with the code
        proves only that they agree."""
        order_id = 962
        _order(db, order_id, shipping_id=962)
        self._self_service_shipment(db, 962)
        _payment(db, 105, order_id, status="approved", net_received_amount=Decimal("100"))
        self._logistica(db)
        db.add(CodigoPostalCordon(codigo_postal="1636", cordon="Cordón 1"))
        db.add(
            LogisticaCostoCordon(
                logistica_id=1,
                cordon="Cordon 1",
                costo=Decimal("820.00"),
                vigente_desde=date(2026, 1, 1),
            )
        )
        db.add(
            EtiquetaEnvio(
                shipping_id="962",
                fecha_envio=date(2026, 8, 1),
                logistica_id=1,
                manual_zip_code="1636",
            )
        )
        db.commit()

        result = compute_breakdown(db, [order_id])

        propio_lines = [line for line in result.lines if line.origen == "propio"]
        assert len(propio_lines) == 1, "the accent broke the join -- the tariff never matched"
        assert propio_lines[0].monto == Decimal("820.00")
        assert REASON_FLEX_COST_UNKNOWN not in result.incomplete_reasons

    def test_the_transport_postcode_decides_the_cordon_not_the_buyers(self, db) -> None:
        """When a Transporte is assigned the parcel goes to ITS depot, and
        the carrier is paid for that trip -- so the transport's CP picks the
        tariff. The Etiquetas screens already resolve it this way. Reading
        the buyer's CP lands on a different cordon, a different tariff and a
        different cost for the same `shipping_id`: two prices, one
        shipment."""
        order_id = 964
        _order(db, order_id, shipping_id=964)
        self._self_service_shipment(db, 964)
        _payment(db, 107, order_id, status="approved", net_received_amount=Decimal("100"))
        self._logistica(db)
        db.add(Transporte(id=1, nombre="Cruz del Sur", cp="8000"))
        # The buyer is in cordon 1; the transport depot is in cordon 3.
        db.add(CodigoPostalCordon(codigo_postal="1638", cordon="Cordón 1"))
        db.add(CodigoPostalCordon(codigo_postal="8000", cordon="Cordón 3"))
        db.add(
            LogisticaCostoCordon(
                logistica_id=1, cordon="Cordon 1", costo=Decimal("300.00"), vigente_desde=date(2026, 1, 1)
            )
        )
        db.add(
            LogisticaCostoCordon(
                logistica_id=1, cordon="Cordon 3", costo=Decimal("1500.00"), vigente_desde=date(2026, 1, 1)
            )
        )
        db.add(
            EtiquetaEnvio(
                shipping_id="964",
                fecha_envio=date(2026, 8, 1),
                logistica_id=1,
                transporte_id=1,
                manual_zip_code="1638",
            )
        )
        db.commit()

        result = compute_breakdown(db, [order_id])

        propio_lines = [line for line in result.lines if line.origen == "propio"]
        assert len(propio_lines) == 1
        assert propio_lines[0].monto == Decimal("1500.00"), "the buyer's CP was used instead of the transport's"

    def test_turbo_label_costs_the_turbo_tariff_not_the_plain_one(self, db) -> None:
        """The tariff's plain `costo` is not what a turbo shipment costs us.
        Reading it would show a number that disagrees with the Etiquetas
        screen for the very same `shipping_id`."""
        order_id = 963
        _order(db, order_id, shipping_id=963)
        self._self_service_shipment(db, 963)
        _payment(db, 106, order_id, status="approved", net_received_amount=Decimal("100"))
        self._logistica(db)
        db.add(CodigoPostalCordon(codigo_postal="1637", cordon="Cordón 2"))
        db.add(
            LogisticaCostoCordon(
                logistica_id=1,
                cordon="Cordon 2",
                costo=Decimal("500.00"),
                costo_turbo=Decimal("900.00"),
                vigente_desde=date(2026, 1, 1),
            )
        )
        db.add(
            EtiquetaEnvio(
                shipping_id="963",
                fecha_envio=date(2026, 8, 1),
                logistica_id=1,
                manual_zip_code="1637",
                es_turbo=True,
            )
        )
        db.commit()

        result = compute_breakdown(db, [order_id])

        propio_lines = [line for line in result.lines if line.origen == "propio"]
        assert len(propio_lines) == 1
        assert propio_lines[0].monto == Decimal("900.00")

    def test_mixed_pack_still_charges_the_flex_order(self, db) -> None:
        """A pack whose orders disagree collapses to `"mixed"`, and keying
        the Flex resolver off that collapsed value dropped the cost with NO
        line and NO `flex_cost_unknown` -- a freight cost we really pay,
        gone without a trace. Selection is per order, so the self_service
        member still gets charged even when its packmate is not Flex."""
        flex_order, other_order = 958, 959
        _order(db, flex_order, shipping_id=958, pack_id=9580)
        _order(db, other_order, shipping_id=959, pack_id=9580)
        self._self_service_shipment(db, 958)
        db.add(MlShipmentOps(shipment_id=959, logistic_type="cross_docking"))
        _payment(db, 103, flex_order, status="approved", net_received_amount=Decimal("100"))
        self._logistica(db)
        db.add(
            EtiquetaEnvio(
                shipping_id="958",
                fecha_envio=date(2026, 8, 1),
                logistica_id=1,
                costo_override=Decimal("640.00"),
            )
        )
        db.commit()

        result = compute_breakdown(db, [flex_order, other_order])

        propio_lines = [line for line in result.lines if line.origen == "propio"]
        assert len(propio_lines) == 1
        assert propio_lines[0].monto == Decimal("640.00")
        # The cost RESOLVED, so the unknown reason must be absent: a line
        # plus the reason would be the sale claiming both at once.
        assert REASON_FLEX_COST_UNKNOWN not in result.incomplete_reasons

    def test_mixed_pack_with_unresolved_flex_says_so(self, db) -> None:
        """Same shape, but the Flex member has no label: the cost is UNKNOWN
        and must be reported as such. Silence would be the same hole the
        test above closes, just wearing a different disguise."""
        flex_order, other_order = 960, 961
        _order(db, flex_order, shipping_id=960, pack_id=9600)
        _order(db, other_order, shipping_id=961, pack_id=9600)
        self._self_service_shipment(db, 960)
        db.add(MlShipmentOps(shipment_id=961, logistic_type="cross_docking"))
        _payment(db, 104, flex_order, status="approved", net_received_amount=Decimal("100"))
        db.commit()

        result = compute_breakdown(db, [flex_order, other_order])

        assert not [line for line in result.lines if line.origen == "propio"]
        assert REASON_FLEX_COST_UNKNOWN in result.incomplete_reasons

    def test_flex_cost_from_tariff_table(self, db) -> None:
        order_id = 951
        _order(db, order_id, shipping_id=951)
        self._self_service_shipment(db, 951)
        _payment(db, 96, order_id, status="approved", net_received_amount=Decimal("100"))
        self._logistica(db)
        db.add(CodigoPostalCordon(codigo_postal="1900", cordon="Cordon 1"))
        db.add(
            LogisticaCostoCordon(
                logistica_id=1,
                cordon="Cordon 1",
                costo=Decimal("500.00"),
                vigente_desde=date(2026, 1, 1),
            )
        )
        db.add(
            EtiquetaEnvio(
                shipping_id="951",
                fecha_envio=date(2026, 8, 1),
                logistica_id=1,
                manual_zip_code="1900",
            )
        )
        db.commit()

        result = compute_breakdown(db, [order_id])

        propio_lines = [line for line in result.lines if line.origen == "propio"]
        assert len(propio_lines) == 1
        assert propio_lines[0].monto == Decimal("500.00")
        assert REASON_FLEX_COST_UNKNOWN not in result.incomplete_reasons

    def test_flex_cost_unknown_no_label(self, db) -> None:
        order_id = 952
        _order(db, order_id, shipping_id=952)
        self._self_service_shipment(db, 952)
        _payment(db, 97, order_id, status="approved", net_received_amount=Decimal("100"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert not any(line.origen == "propio" for line in result.lines)
        assert REASON_FLEX_COST_UNKNOWN in result.incomplete_reasons

    def test_flex_cost_unknown_no_logistica(self, db) -> None:
        order_id = 953
        _order(db, order_id, shipping_id=953)
        self._self_service_shipment(db, 953)
        _payment(db, 98, order_id, status="approved", net_received_amount=Decimal("100"))
        db.add(EtiquetaEnvio(shipping_id="953", fecha_envio=date(2026, 8, 1)))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert not any(line.origen == "propio" for line in result.lines)
        assert REASON_FLEX_COST_UNKNOWN in result.incomplete_reasons

    def test_flex_cost_unknown_no_tariff_row(self, db) -> None:
        order_id = 954
        _order(db, order_id, shipping_id=954)
        self._self_service_shipment(db, 954)
        _payment(db, 99, order_id, status="approved", net_received_amount=Decimal("100"))
        self._logistica(db)
        db.add(CodigoPostalCordon(codigo_postal="1901", cordon="Cordon 2"))
        db.add(
            EtiquetaEnvio(
                shipping_id="954",
                fecha_envio=date(2026, 8, 1),
                logistica_id=1,
                manual_zip_code="1901",
            )
        )
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert not any(line.origen == "propio" for line in result.lines)
        assert REASON_FLEX_COST_UNKNOWN in result.incomplete_reasons

    def test_flex_cost_unknown_no_postcode(self, db) -> None:
        order_id = 955
        _order(db, order_id, shipping_id=955)
        self._self_service_shipment(db, 955)
        _payment(db, 100, order_id, status="approved", net_received_amount=Decimal("100"))
        self._logistica(db)
        db.add(EtiquetaEnvio(shipping_id="955", fecha_envio=date(2026, 8, 1), logistica_id=1))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert not any(line.origen == "propio" for line in result.lines)
        assert REASON_FLEX_COST_UNKNOWN in result.incomplete_reasons


class TestMontoOperacion:
    """`monto_operacion` -- the gross the drawer opens on: THE SUM OF THE
    PRODUCTS, the figure ML's own screen heads its breakdown with.

    It is NOT `paid_amount`. That was the first implementation and it was a
    mis-specification: `paid_amount` is what the BUYER paid, freight
    included when the buyer pays it, so the product lines legitimately fell
    short of it and the panel warned "los ítems no suman el total" on
    ordinary sales. `paid_amount` is still the base of the money identity
    this module reconciles against; it is just not this heading.

    `None`, never a fabricated 0, whenever any item's price is unknown."""

    def test_single_order_reports_the_products_total(self, db) -> None:
        order_id = 700
        _order(db, order_id, paid_amount=Decimal("19900.00"))
        _payment(db, 1, order_id, status="approved", net_received_amount=Decimal("19900.00"))
        _item(db, order_id, "MLA1", quantity=1, unit_price=Decimal("19900.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.monto_operacion == Decimal("19900.00")

    def test_quantity_counts(self, db) -> None:
        """Two units of a $100 product is $200, not $100 -- the heading is a
        sum of LINES, not of unit prices."""
        order_id = 705
        _order(db, order_id, paid_amount=Decimal("200.00"))
        _payment(db, 1, order_id, status="approved", net_received_amount=Decimal("200.00"))
        _item(db, order_id, "MLA1", quantity=2, unit_price=Decimal("100.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.monto_operacion == Decimal("200.00")

    def test_pack_sums_the_products_of_every_member_order(self, db) -> None:
        pack_id = 701
        order_a, order_b = 7010, 7011
        _order(db, order_a, pack_id=pack_id, paid_amount=Decimal("1000.00"))
        _order(db, order_b, pack_id=pack_id, paid_amount=Decimal("2500.50"))
        _payment(db, 1, order_a, status="approved", net_received_amount=Decimal("1000.00"))
        _payment(db, 2, order_b, status="approved", net_received_amount=Decimal("2500.50"))
        _item(db, order_a, "MLA1", quantity=1, unit_price=Decimal("1000.00"))
        _item(db, order_b, "MLA2", quantity=1, unit_price=Decimal("2500.50"))
        db.commit()

        result = compute_breakdown(db, [order_a, order_b])

        assert result.monto_operacion == Decimal("3500.50")

    def test_a_sale_with_no_items_reports_none_not_zero(self, db) -> None:
        order_id = 702
        _order(db, order_id, paid_amount=Decimal("100.00"))
        _payment(db, 1, order_id, status="approved", net_received_amount=Decimal("100.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.monto_operacion is None

    def test_one_unpriced_item_makes_the_pack_total_unknown(self, db) -> None:
        """A partial sum would UNDERSTATE the gross -- silently dropping the
        unpriced item's money instead of saying so."""
        pack_id = 703
        order_a, order_b = 7030, 7031
        _order(db, order_a, pack_id=pack_id, paid_amount=Decimal("1000.00"))
        _order(db, order_b, pack_id=pack_id, paid_amount=Decimal("500.00"))
        _payment(db, 1, order_a, status="approved", net_received_amount=Decimal("1000.00"))
        _item(db, order_a, "MLA1", quantity=1, unit_price=Decimal("1000.00"))
        _item(db, order_b, "MLA2", quantity=1, unit_price=None)
        db.commit()

        result = compute_breakdown(db, [order_a, order_b])

        assert result.monto_operacion is None


class TestItemLines:
    """Per-item breakdown of `monto_operacion` -- product-owner request:
    "no están desglosados, no sé de qué es cada cosa". Mirrors this
    module's own house rule (see REASON_ITEM_LINES_* docstring): a list
    that LOOKS complete but does not sum to the total above it must say so,
    never render silently."""

    def test_lines_sum_to_monto_operacion(self, db) -> None:
        order_id = 800
        _order(db, order_id, paid_amount=Decimal("300.00"))
        _payment(db, 1, order_id, status="approved", net_received_amount=Decimal("300.00"))
        _item(db, order_id, "MLA1", quantity=2, unit_price=Decimal("100.00"))
        _item(db, order_id, "MLA2", quantity=1, unit_price=Decimal("100.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.item_lines_reconcilia is True
        assert result.item_lines_razon is None
        total = sum((line.monto for line in result.item_lines), Decimal("0"))
        assert total == result.monto_operacion == Decimal("300.00")

    def test_item_without_unit_price_marks_lines_unreliable(self, db) -> None:
        order_id = 801
        _order(db, order_id, paid_amount=Decimal("300.00"))
        _payment(db, 1, order_id, status="approved", net_received_amount=Decimal("300.00"))
        _item(db, order_id, "MLA1", quantity=1, unit_price=Decimal("100.00"))
        _item(db, order_id, "MLA2", quantity=1, unit_price=None)
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.item_lines_reconcilia is False
        assert result.item_lines_razon == REASON_ITEM_LINES_ITEM_SIN_PRECIO
        # The unpriced item is still LISTED (with monto=None), never dropped.
        assert len(result.item_lines) == 2
        assert any(line.monto is None for line in result.item_lines)

    def test_no_items_marks_lines_unreliable(self, db) -> None:
        order_id = 802
        _order(db, order_id, paid_amount=Decimal("300.00"))
        _payment(db, 1, order_id, status="approved", net_received_amount=Decimal("300.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.item_lines == []
        assert result.item_lines_reconcilia is False
        assert result.item_lines_razon == REASON_ITEM_LINES_NO_ITEMS

    def test_monto_operacion_is_the_items_own_sum(self, db) -> None:
        """The heading IS the products' sum, so it cannot disagree with the
        list under it -- there is no comparison left to fail.

        It used to be `paid_amount`, and that was a mis-specification, not a
        second valid reading: `paid_amount` is what the BUYER paid, freight
        included when the buyer pays it, so the item lines legitimately fell
        short and the panel warned "los ítems no suman el total" on ordinary
        sales. `paid_amount` here is deliberately a DIFFERENT number from
        the items' total, and the heading must follow the items.
        """
        order_id = 803
        _order(db, order_id, paid_amount=Decimal("999.00"))
        _payment(db, 1, order_id, status="approved", net_received_amount=Decimal("999.00"))
        _item(db, order_id, "MLA1", quantity=2, unit_price=Decimal("100.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.monto_operacion == Decimal("200.00")
        assert result.item_lines_reconcilia is True
        assert result.item_lines_razon is None

    def test_an_unpriced_item_leaves_the_heading_unknown_not_partial(self, db) -> None:
        """A partial sum under a heading that looks complete is the failure
        this module refuses to build: with one price missing the heading is
        `None`, not the total of the items that happen to have one."""
        order_id = 804
        _order(db, order_id, paid_amount=Decimal("999.00"))
        _payment(db, 1, order_id, status="approved", net_received_amount=Decimal("999.00"))
        _item(db, order_id, "MLA1", quantity=1, unit_price=Decimal("100.00"))
        _item(db, order_id, "MLA2", quantity=1, unit_price=None)
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.monto_operacion is None
        assert result.item_lines_reconcilia is False
        assert result.item_lines_razon == REASON_ITEM_LINES_ITEM_SIN_PRECIO


class TestItemWithoutQuantityIsItsOwnReason:
    def test_a_priced_item_with_no_quantity_is_not_reported_as_unpriced(self, db) -> None:
        """ "Sin precio" and "sin cantidad" get fixed in different places.
        Sending a reader to look for a missing price on an item that HAS
        one wastes the trip, and the skip breakdown is the only observable
        output this panel gives them.

        MUTATION-VERIFIED: collapsing both back into
        `REASON_ITEM_LINES_ITEM_SIN_PRECIO` turns this red.
        """
        order_id = 810
        _order(db, order_id, paid_amount=Decimal("100.00"))
        _payment(db, 1, order_id, status="approved", net_received_amount=Decimal("100.00"))
        _item(db, order_id, "MLA1", quantity=None, unit_price=Decimal("100.00"))
        db.commit()

        result = compute_breakdown(db, [order_id])

        assert result.item_lines_reconcilia is False
        assert result.item_lines_razon == REASON_ITEM_LINES_ITEM_SIN_CANTIDAD
        assert result.monto_operacion is None


class TestAPackMemberWithNoItems:
    def test_a_sibling_order_without_items_is_not_summed_over_silently(self, db) -> None:
        """On a pack where one order has items and a sibling has none,
        `order_items` is NOT empty -- a bare `if not order_items` walks
        straight past it and sums only the orders that loaded, presenting a
        partial total as the operation's own.

        MUTATION-VERIFIED: dropping the per-order coverage check turns this
        red, and `monto_operacion` comes back as the partial 1000 instead
        of unknown.
        """
        pack_id = 705
        order_a, order_b = 7050, 7051
        _order(db, order_a, pack_id=pack_id, paid_amount=Decimal("1000.00"))
        _order(db, order_b, pack_id=pack_id, paid_amount=Decimal("500.00"))
        _payment(db, 1, order_a, status="approved", net_received_amount=Decimal("1000.00"))
        _item(db, order_a, "MLA1", quantity=1, unit_price=Decimal("1000.00"))
        # order_b carries NO items at all.
        db.commit()

        result = compute_breakdown(db, [order_a, order_b])

        assert result.item_lines_reconcilia is False
        assert result.item_lines_razon == REASON_ITEM_LINES_ORDEN_SIN_ITEMS
        assert result.monto_operacion is None


class TestLinesSurviveAnUnformableTotal:
    def test_a_pack_with_one_empty_order_still_lists_what_it_does_have(self, db) -> None:
        """The flag withholds the TOTAL, not the detail.

        Dropping the lines when the total cannot be formed leaves the
        reader with a warning and a blank list -- strictly less than we
        know. The items that DID load are still real.
        """
        pack_id = 706
        order_a, order_b = 7060, 7061
        _order(db, order_a, pack_id=pack_id, paid_amount=Decimal("1000.00"))
        _order(db, order_b, pack_id=pack_id, paid_amount=Decimal("500.00"))
        _payment(db, 1, order_a, status="approved", net_received_amount=Decimal("1000.00"))
        _item(db, order_a, "MLA1", quantity=1, unit_price=Decimal("1000.00"))
        db.commit()

        result = compute_breakdown(db, [order_a, order_b])

        assert [line.item_id for line in result.item_lines] == ["MLA1"]
        assert result.item_lines_reconcilia is False
        assert result.item_lines_razon == REASON_ITEM_LINES_ORDEN_SIN_ITEMS
        assert result.monto_operacion is None


# Production payments, values as stored (both fully refunded; no partial
# refund carrying a SIRTAC charge was found in production on 2026-09-21).
_REFUNDED_WITH_SIRTAC = {
    # payment 180185789862 / order 2000018573170546
    "neuquen": (
        180185789862,
        2000018573170546,
        "84955.89",
        "132510.00",
        (
            ("financing_add_on_fee", "fee", "17756.34"),
            ("meli_percentage_fee", "fee", "19015.18"),
            ("shp_cross_docking", "shipping", "9590.00"),
            ("tax_withholding_collector-debitos_creditos", "tax", "795.06"),
            ("tax_withholding_sirtac-neuquen", "tax", "397.53"),
        ),
    ),
    # payment 180131208268 / order 2000018567271536: SIRTAC AND a generic
    # "Retención" (no regime) on the same payment.
    "santa_fe_generic": (
        180131208268,
        2000018567271536,
        "10163.18",
        "13999.00",
        (
            ("flat_fee", "fee", "1330.00"),
            ("meli_percentage_fee", "fee", "2169.84"),
            ("tax_withholding_collector-debitos_creditos", "tax", "83.99"),
            ("tax_withholding-santa_fe", "tax", "209.99"),
            ("tax_withholding_sirtac-santa_fe", "tax", "42.00"),
        ),
    ),
}


class TestRefundBranchWithSirtac:
    """`payment_effective_net`'s refund branch: `seller_refunded` already
    gives back the refunded share of SIRTAC, and the add-back returns only
    `amount - refunded`. On a full refund the two compose to zero -- a sale
    that was returned left nothing, SIRTAC included. Every earlier SIRTAC
    refund test set `refunded` on the charge with the payment's
    `transaction_amount_refunded` at 0, so none ran this branch."""

    @pytest.mark.parametrize("case", sorted(_REFUNDED_WITH_SIRTAC))
    def test_fully_refunded_payment_with_sirtac_nets_zero_on_every_path(self, db, case) -> None:
        payment_id, order_id, net, refunded_total, charges = _REFUNDED_WITH_SIRTAC[case]
        _order(db, order_id)
        _payment(
            db,
            payment_id,
            order_id,
            status="refunded",
            net_received_amount=Decimal(net),
            transaction_amount_refunded=Decimal(refunded_total),
        )
        for name, type_, amount in charges:
            _charge(db, payment_id, name, type_, Decimal(amount), refunded=Decimal(amount))
        db.commit()

        breakdown = compute_breakdown(db, [order_id])
        assert breakdown.neto == Decimal("0.00")
        assert breakdown.neto_depositado == Decimal("0.00")
        assert breakdown.retenciones_recuperables == Decimal("0.00")

        # The listing's two bulk paths must agree with the detail on this branch too.
        assert compute_neto_by_order_ids(db, [order_id])[order_id] == Decimal("0.00")
        assert compute_neto_desglose_by_order_ids(db, [order_id])[order_id] == (Decimal("0.00"), Decimal("0.00"))
