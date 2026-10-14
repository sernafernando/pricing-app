"""RED/GREEN -- the seller-funded coupon (`coupon_fee`) in the IVA reconcile.

Since 2026-10-10 about half of ML's sales carry a `coupon_fee` charge
(`type='coupon'`): the part of the buyer's coupon the SELLER funds. ML deducts
it from `net_received_amount`, but the decomposition dropped every
`type='coupon'` charge, so those payments missed by exactly the fee and read
"Este desglose de IVA no reconcilia".

Accounting decision (owner): the sale is invoiced at the FULL price, so the
goods line stays `unit_price * quantity`; the coupon fee is a seller cost ML
does not invoice, so it carries NO IVA credit -- it enters the payment-side
sum at 0%. `neto` and everything built on it do not move: they come from
`net_received_amount`, which already had it deducted.

Every amount comes from the real capture (`_coupon_fee_capture`).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.ml_ventas_desglose.breakdown_service import compute_breakdown, compute_neto_by_order_ids
from app.services.ml_ventas_desglose.iva import descomponer_neto

from ._coupon_fee_capture import (
    APPROVED_COUPON_CODE_FEE_REBATE,
    APPROVED_COUPON_FEE_ONLY,
    CANCELLED_COUPON_CODE_AND_FEE,
    IN_MEDIATION_COUPON_FEE,
    REFUNDED_COUPON_FEE_REBATE,
    REFUNDED_FINANCING_COUPON_FEE,
    capture,
    coupon_fee_amount,
    seed_capture,
)

# The user-facing label is the contract the drawer renders as-is.
CUPON_VENDEDOR = "Cupón a cargo del vendedor"

APPROVED = [APPROVED_COUPON_FEE_ONLY, APPROVED_COUPON_CODE_FEE_REBATE]


@pytest.mark.parametrize("payment_id", APPROVED)
class TestTheSellerCouponCloses:
    def test_the_payment_reconciles_to_the_cent(self, db, payment_id) -> None:
        order_id = seed_capture(db, payment_id)

        result = descomponer_neto(db, [order_id])[order_id]

        assert result.diferencia == Decimal("0")
        assert result.reconcilia is True
        assert result.razones == []
        assert result.neto_sin_iva is not None

    def test_the_coupon_fee_is_a_seller_charge_without_iva(self, db, payment_id) -> None:
        order_id = seed_capture(db, payment_id)

        result = descomponer_neto(db, [order_id])[order_id]

        (componente,) = [c for c in result.componentes if c.concepto == CUPON_VENDEDOR]
        amount = coupon_fee_amount(payment_id)
        assert componente.bruto == -amount
        # No fiscal credit: ML does not invoice it, so all of it is base.
        assert componente.alicuota == Decimal("0")
        assert componente.iva == Decimal("0")
        assert componente.base == -amount
        # Inside the payment-side sum, not beside it.
        assert componente.informativo is False
        assert componente.fuera_del_pago is False

    def test_the_neto_does_not_move(self, db, payment_id) -> None:
        """`neto` is `net_received_amount` (+ the SIRTAC add-back), which
        already had the coupon fee deducted by ML."""
        order_id = seed_capture(db, payment_id)
        data = capture(payment_id)
        sirtac = sum(
            (Decimal(str(c["amount"])) for c in data["charges"] if c["name"].startswith("tax_withholding_sirtac-")),
            Decimal("0"),
        )

        neto = compute_neto_by_order_ids(db, [order_id])[order_id]

        assert neto == Decimal(str(data["net_received_amount"])) + sirtac
        assert compute_breakdown(db, [order_id]).neto == neto

    def test_the_goods_stay_at_the_full_price(self, db, payment_id) -> None:
        """Invoiced at the full price without the coupon: the goods line (and
        the "% de varios" base built on it) is `unit_price * quantity`."""
        order_id = seed_capture(db, payment_id)
        data = capture(payment_id)
        full_price = sum(
            (Decimal(str(i["unit_price"])) * i["quantity"] for i in data["items"]),
            Decimal("0"),
        )

        result = descomponer_neto(db, [order_id])[order_id]

        assert sum((c.bruto for c in result.componentes if c.concepto == "Venta"), Decimal("0")) == full_price

    def test_the_panel_shows_the_coupon_as_a_charge(self, db, payment_id) -> None:
        order_id = seed_capture(db, payment_id)

        breakdown = compute_breakdown(db, [order_id])

        (linea,) = [line for line in breakdown.lines if line.concepto == CUPON_VENDEDOR]
        assert linea.monto == coupon_fee_amount(payment_id)
        assert linea.origen == "api"


class TestTheBuyerSideCouponsStayOut:
    """`coupon_code` (the buyer's discount) and `coupon_rebate` (ML's share)
    are NOT seller costs: the full-price goods line already carries them. On
    payment 183081084229 the payment side closes with ONLY the coupon fee:

        23123 (goods) + 2396 (buyer shipping)
        - 2740 - 3412.02 - 390 (fees, Flex)  - 153.11 (débitos/créditos)
        - 1109.95 (coupon_fee)
        == 17560.81 == 17637.36 + 76.56 (SIRTAC add-back) - 153.11 (retiro)

    Adding `coupon_code` (1109.95) or `coupon_rebate` (924) would break it."""

    def test_only_the_coupon_fee_becomes_a_component(self, db) -> None:
        order_id = seed_capture(db, APPROVED_COUPON_CODE_FEE_REBATE)

        result = descomponer_neto(db, [order_id])[order_id]

        cupones = [c for c in result.componentes if c.concepto == CUPON_VENDEDOR]
        assert [c.bruto for c in cupones] == [Decimal("-1109.95")]
        assert Decimal("-924.00") not in {c.bruto for c in result.componentes}


class TestACancelledPaymentContributesNothing:
    def test_its_coupon_fee_is_not_a_component(self, db) -> None:
        """A cancelled payment is not relevant at all (its net is 0), so its
        coupon fee must not appear either."""
        order_id = seed_capture(db, CANCELLED_COUPON_CODE_AND_FEE)

        result = descomponer_neto(db, [order_id])[order_id]

        assert result.componentes == []
        assert result.diferencia is None
        assert all(line.concepto != CUPON_VENDEDOR for line in compute_breakdown(db, [order_id]).lines)


class TestAMediatedSaleClosesLikeAnApprovedOne:
    """`in_mediation` is money collected and held (nothing refunded), so the
    same identity as `neto` applies. Payment 183792389650:

        40500 (goods) - 5963.62 (fee) - 243 (débitos/créditos) - 2025 (coupon_fee)
        - 243 (retiro) == 32025.38 == 32146.88 + 121.50 (SIRTAC) - 243

    Without the coupon fee it missed by exactly -2025."""

    def test_it_reconciles_with_the_coupon_fee(self, db) -> None:
        order_id = seed_capture(db, IN_MEDIATION_COUPON_FEE)

        result = descomponer_neto(db, [order_id])[order_id]

        assert result.diferencia == Decimal("0")
        assert result.reconcilia is True
        assert result.razones == []
        assert [c.bruto for c in result.componentes if c.concepto == CUPON_VENDEDOR] == [Decimal("-2025.00")]
        assert compute_neto_by_order_ids(db, [order_id])[order_id] == Decimal("32268.38")


@pytest.mark.parametrize(
    ("payment_id", "neto", "diferencia"),
    [
        # Pinned to what main computed for these orders BEFORE the coupon
        # change -- the change must not move a single figure of a refunded sale.
        #
        # The negative `neto` (exactly -coupon_fee) is PRE-EXISTING and NOT
        # touched here: `payment_effective_net` adds back only the refunds of
        # `is_seller_charge` charges, and `coupon_fee` is not one, so its
        # refund is missing from the identity. Pinned so a fix there is a
        # deliberate, visible change.
        (REFUNDED_FINANCING_COUPON_FEE, Decimal("-20000.00"), Decimal("-519999.00")),
        (REFUNDED_COUPON_FEE_REBATE, Decimal("-1579.95"), Decimal("-34494.95")),
    ],
)
class TestARefundedSaleIsUnchanged:
    """Every captured refunded payment refunds its `coupon_fee` in full, so its
    net amount is zero and it adds no component and no panel line."""

    def test_the_decomposition_is_what_it_was_before(self, db, payment_id, neto, diferencia) -> None:
        order_id = seed_capture(db, payment_id)

        result = descomponer_neto(db, [order_id])[order_id]

        assert result.razones == ["venta_con_devolucion"]
        assert result.reconcilia is False
        assert result.diferencia == diferencia
        assert result.neto_sin_iva is None
        assert all(c.concepto != CUPON_VENDEDOR for c in result.componentes)
        assert compute_neto_by_order_ids(db, [order_id])[order_id] == neto

    def test_a_fully_refunded_coupon_fee_shows_no_panel_line(self, db, payment_id, neto, diferencia) -> None:
        """Panel and IVA decomposition agree: no zero `Cupón a cargo del
        vendedor` row on either surface."""
        order_id = seed_capture(db, payment_id)

        breakdown = compute_breakdown(db, [order_id])

        assert all(line.concepto != CUPON_VENDEDOR for line in breakdown.lines)
        assert breakdown.neto == neto
