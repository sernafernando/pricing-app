"""RED/GREEN -- the shipping the BUYER pays enters the "% de varios" base
(ventas-ml-varios-base-envio).

Rule (confirmed by the user): base = operation without IVA + (shipping paid by
the buyer + the Flex bonificación) / 1.21. The shipping counts GROSS -- even
when ML charges it back (+990 / -990) -- and its IVA is never subtracted as an
expense.

ONE source for the shipping: `payment.shipping_amount`, the explicit ML field
and the one the visible IVA line already reads. Not `paid_amount -
total_amount` (it would also catch a financing surcharge) and not
`raw_costs.receiver.cost` (ML annulled the Flex pack's 2216.30 and it still
says so). Every fixture is a REAL capture (`_envio_comprador_capture.py`).
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import pytest

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrdersOps
from app.models.varios_venta_pct import VariosVentaPct
from app.services.ml_ventas_desglose import envio_comprador
from app.services.ml_ventas_desglose.envio_comprador import envio_comprador_de_pago
from app.services.ml_ventas_desglose.iva import CONCEPTO_ENVIO_COMPRADOR, descomponer_neto
from app.services.order_metrics.compute import compute_order_metrics

from ._envio_comprador_capture import (
    CROSS_DOCKING,
    FULFILLMENT_3990,
    FULFILLMENT_990,
    SELF_SERVICE_4990,
    SELF_SERVICE_PACK,
    THREE_PAYMENTS,
    capture,
    seed_case,
)

GOODS_990 = Decimal("15165.29")  # 18350 / 1.21, HALF_UP
SHIPPING_NET_990 = Decimal("818.18")  # 990 / 1.21, HALF_UP


class TestTheFulfillmentCaseThatNetsToZero:
    def test_the_base_is_the_goods_plus_the_gross_shipping_without_iva(self, db) -> None:
        """Buyer paid 990 and ML charged `shp_fulfillment` 990 back: it nets
        to zero and STILL goes into the base (we invoice it, we pay IIBB on
        it). MUTATION: reading the shipping net of the charge makes it 0."""
        seed_case(db, FULFILLMENT_990)

        desc = descomponer_neto(db, [FULFILLMENT_990])[FULFILLMENT_990]

        assert desc.base_venta_sin_iva == GOODS_990  # untouched: the goods only
        assert desc.base_varios == GOODS_990 + SHIPPING_NET_990


class TestReadingOnePaymentsShipping:
    @pytest.mark.parametrize("amount,expected", [(Decimal("990.00"), "990.00"), (4699.09, "4699.09"), (5373, "5373")])
    def test_a_positive_number_is_the_shipping(self, amount, expected) -> None:
        assert envio_comprador_de_pago(amount, 1) == Decimal(expected)

    @pytest.mark.parametrize("amount", [None, 0, Decimal("0.00"), 0.0])
    def test_nothing_paid_is_nothing_and_not_a_warning(self, amount, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger=envio_comprador.__name__):
            assert envio_comprador_de_pago(amount, 1) is None
        assert caplog.text == ""

    @pytest.mark.parametrize(
        "bad",
        ["990", "abc", -1, Decimal("-990.5"), True, False, float("nan"), float("inf"), Decimal("NaN"), [990]],
        ids=repr,
    )
    def test_an_unreadable_amount_never_invents_base(self, bad, caplog) -> None:
        """Fail-closed: add nothing and name the payment."""
        with caplog.at_level(logging.WARNING, logger=envio_comprador.__name__):
            assert envio_comprador_de_pago(bad, 777) is None
        assert "777" in caplog.text


# ---------------------------------------------------------------------------
# The "% de varios" over the new base
# ---------------------------------------------------------------------------


def _varios(db, pct: str) -> None:
    db.add(VariosVentaPct(porcentaje=Decimal(pct), fecha_desde=date(2026, 1, 1), fecha_hasta=None))
    db.commit()


def _varios_line(metrics) -> Decimal:
    return next(monto for code, monto, _c in metrics.lineas if code == "varios")


class TestVariosOverTheNewBase:
    def test_the_990_case_applies_the_percentage_over_goods_plus_shipping(self, db) -> None:
        """2% of (15165.29 + 818.18) = 319.67, not 2% of the goods (303.31).
        MUTATION: keeping `base = venta_sin_iva` fails this."""
        seed_case(db, FULFILLMENT_990)
        _varios(db, "2.00")

        metrics = compute_order_metrics(db, [FULFILLMENT_990])[FULFILLMENT_990]

        assert _varios_line(metrics) == Decimal("319.67")

    def test_the_flex_pack_is_the_goods_plus_the_599_bonificacion_and_no_buyer_shipping(self, db) -> None:
        """Pack 2000015400388457: the buyer's 2216.30 was annulled (adds 0),
        ML's bonificación is 599, not the 3773.7 `ratio` subsidy. Base =
        105998/1.21 + 599/1.21 = 87601.65 + 495.04. 2% = 1761.93."""
        seed_case(db, SELF_SERVICE_PACK)
        _varios(db, "2.00")

        desc = descomponer_neto(db, [SELF_SERVICE_PACK])[SELF_SERVICE_PACK]
        metrics = compute_order_metrics(db, [SELF_SERVICE_PACK])[SELF_SERVICE_PACK]

        assert desc.base_venta_sin_iva == Decimal("87601.65")
        assert desc.base_varios == Decimal("87601.65") + Decimal("495.04")
        assert [c.concepto for c in desc.componentes if c.informativo and c.alicuota is not None] == [
            "Bonificación por envío"
        ]
        assert _varios_line(metrics) == Decimal("1761.93")

    def test_buyer_shipping_and_bonificacion_both_enter_once_each(self, db) -> None:
        """No captured sale has both. The mechanics are proved on the 4990
        self_service order, given the REAL Flex payload of the captured pack
        (sender discount 599): base = goods + 4990/1.21 + 599/1.21."""
        flex_costs = capture(SELF_SERVICE_PACK)["db"]["shipments"][0]["raw_costs"]
        seed_case(db, SELF_SERVICE_4990, raw_costs=flex_costs)

        desc = descomponer_neto(db, [SELF_SERVICE_4990])[SELF_SERVICE_4990]

        assert desc.base_venta_sin_iva == Decimal("12066.12")  # 14600 / 1.21
        assert desc.base_varios == Decimal("12066.12") + Decimal("4123.97") + Decimal("495.04")

    def test_the_shipping_adds_no_deduction_of_its_own_to_the_chain(self, db) -> None:
        """The shipping IVA is informational: with 0% varios the Total Gauss is
        exactly `neto_sin_iva` minus the chain's own lines (the shipping is
        already inside the net, and nothing subtracts it again)."""
        seed_case(db, FULFILLMENT_990)

        metrics = compute_order_metrics(db, [FULFILLMENT_990])[FULFILLMENT_990]

        assert metrics.neto_sin_iva is not None
        assert metrics.total_gauss == metrics.neto_sin_iva - sum(m for _c, m, _x in metrics.lineas)
        assert [code for code, _m, _x in metrics.lineas] == ["costo_mercaderia", "varios"]

    def test_the_visible_line_is_the_existing_one_and_no_second_line_is_added(self, db) -> None:
        """`iva.py` already shows the buyer's shipping as a visible line
        (`payment.shipping_amount`, inside the net) with its gross / base /
        IVA: it is NOT duplicated by a second, informational one."""
        seed_case(db, FULFILLMENT_990)

        desc = descomponer_neto(db, [FULFILLMENT_990])[FULFILLMENT_990]

        lines = [c for c in desc.componentes if "nvío" in c.concepto and "comprador" in c.concepto]
        assert len(lines) == 1
        assert lines[0].concepto == CONCEPTO_ENVIO_COMPRADOR
        assert (lines[0].bruto, lines[0].base, lines[0].iva) == (
            Decimal("990.00"),
            Decimal("818.18"),
            Decimal("171.82"),
        )
        assert desc.reconcilia is True

    def test_no_shipping_paid_means_no_line(self, db) -> None:
        seed_case(db, SELF_SERVICE_PACK)

        desc = descomponer_neto(db, [SELF_SERVICE_PACK])[SELF_SERVICE_PACK]

        assert CONCEPTO_ENVIO_COMPRADOR not in [c.concepto for c in desc.componentes]

    @pytest.mark.parametrize(
        "case,bruto",
        [
            (FULFILLMENT_990, "990"),
            (CROSS_DOCKING, "4699.09"),
            (FULFILLMENT_3990, "3990"),
            (SELF_SERVICE_4990, "4990"),
            (SELF_SERVICE_PACK, None),
            (THREE_PAYMENTS, "5373.7"),
        ],
    )
    def test_the_captured_cases_and_the_line_and_the_base_agree(self, db, case, bruto) -> None:
        """The three payments of `THREE_PAYMENTS` (one rejected, one without
        shipping) count the shipping ONCE; the annulled Flex pack has none."""
        seed_case(db, case)

        desc = descomponer_neto(db, [case])[case]

        line = sum((c.bruto for c in desc.componentes if c.concepto == CONCEPTO_ENVIO_COMPRADOR), Decimal("0"))
        if bruto is None:
            assert desc.envio_comprador is None
            assert line == 0
        else:
            assert desc.envio_comprador.bruto == line == Decimal(bruto)

    def test_an_unresolved_goods_base_stays_unresolved_whatever_the_shipping(self, db) -> None:
        """The shipping can only add to a goods side we trust."""
        seed_case(db, FULFILLMENT_990)
        db.query(MlOrderItemCosto).filter_by(order_id=FULFILLMENT_990).delete()
        db.commit()

        desc = descomponer_neto(db, [FULFILLMENT_990])[FULFILLMENT_990]

        assert desc.base_venta_sin_iva is None
        assert desc.base_varios is None


class TestTheBaseFollowsShippingAmountNotTheDifference:
    """ONE source for the buyer's shipping: the explicit ML field
    `payment.shipping_amount`, the same one the visible line reads.
    `paid_amount - total_amount` is an inference that also catches a financing
    surcharge."""

    def test_a_surcharge_in_paid_amount_is_not_shipping(self, db) -> None:
        seed_case(db, FULFILLMENT_990)
        order = db.query(MlOrdersOps).filter_by(order_id=FULFILLMENT_990).one()
        order.paid_amount = order.paid_amount + Decimal("500")  # e.g. financing interest
        db.commit()

        desc = descomponer_neto(db, [FULFILLMENT_990])[FULFILLMENT_990]

        assert desc.base_varios == GOODS_990 + SHIPPING_NET_990
        assert desc.envio_comprador.bruto == Decimal("990.00")

    def test_the_base_follows_the_payment_field_when_the_difference_disagrees(self, db) -> None:
        from app.models.ml_payments import MlPaymentOps

        seed_case(db, FULFILLMENT_990)
        db.query(MlPaymentOps).filter_by(order_id=FULFILLMENT_990).update({"shipping_amount": Decimal("1200")})
        db.commit()

        desc = descomponer_neto(db, [FULFILLMENT_990])[FULFILLMENT_990]

        assert desc.base_varios == GOODS_990 + Decimal("991.74")  # 1200 / 1.21

    def test_the_base_and_the_line_count_several_payments_the_same_way(self, db) -> None:
        """Two relevant payments each carrying shipping: the line has one
        component per payment and the base is the sum of THEIR bases."""
        from app.models.ml_payments import MlPaymentOps

        seed_case(db, FULFILLMENT_990)
        payment = db.query(MlPaymentOps).filter_by(order_id=FULFILLMENT_990).one()
        payment.shipping_amount = Decimal("500")
        db.add(
            MlPaymentOps(
                payment_id=payment.payment_id + 1,
                order_id=FULFILLMENT_990,
                status="approved",
                net_received_amount=Decimal("0"),
                transaction_amount=Decimal("0"),
                shipping_amount=Decimal("490"),
            )
        )
        db.commit()

        desc = descomponer_neto(db, [FULFILLMENT_990])[FULFILLMENT_990]

        line_bases = [c.base for c in desc.componentes if c.concepto == CONCEPTO_ENVIO_COMPRADOR]
        assert len(line_bases) == 2
        assert desc.base_varios == GOODS_990 + sum(line_bases)
        assert desc.envio_comprador.neto == sum(line_bases)

    def test_a_negative_shipping_adds_nothing_and_logs(self, db, caplog) -> None:
        from app.models.ml_payments import MlPaymentOps

        seed_case(db, FULFILLMENT_990)
        payment = db.query(MlPaymentOps).filter_by(order_id=FULFILLMENT_990).one()
        payment.shipping_amount = Decimal("-100")
        db.commit()

        with caplog.at_level(logging.WARNING, logger=envio_comprador.__name__):
            desc = descomponer_neto(db, [FULFILLMENT_990])[FULFILLMENT_990]

        assert desc.base_varios == GOODS_990
        assert desc.envio_comprador is None
        assert str(payment.payment_id) in caplog.text
