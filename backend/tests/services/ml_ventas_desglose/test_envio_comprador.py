"""RED/GREEN -- the shipping the BUYER pays enters the "% de varios" base
(ventas-ml-varios-base-envio).

Rule (confirmed by the user): base = operation without IVA + (shipping paid by
the buyer + the Flex bonificación) / 1.21. The shipping counts GROSS -- even
when ML charges it back (+990 / -990) -- and its IVA is never subtracted as an
expense.

The shipping the buyer paid is the money that CAME IN:
`order.paid_amount - order.total_amount`, per order. `raw_costs.receiver.cost`
is not reliable (ML annulled the 2216.30 of the Flex pack and `receiver.cost`
still says so). Every fixture is a REAL capture (`_envio_comprador_capture.py`).
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
from app.services.ml_ventas_desglose.envio_comprador import (
    envio_comprador_bruto,
    resolve_envio_comprador_by_order_ids,
)
from app.services.ml_ventas_desglose.iva import CONCEPTO_ENVIO_COMPRADOR, IVA_ML_DIVISOR, descomponer_neto
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


class TestReadingWhatTheBuyerPaid:
    @pytest.mark.parametrize(
        "paid,total,expected",
        [
            ("19340", "18350", "990"),
            ("61598.09", "56899", "4699.09"),
            ("48156", "44166", "3990"),
            ("19590", "14600", "4990"),
            ("42443.7", "37070", "5373.70"),
        ],
    )
    def test_the_captured_orders_give_what_came_in(self, paid, total, expected) -> None:
        assert envio_comprador_bruto(Decimal(paid), Decimal(total), 1) == Decimal(expected)

    @pytest.mark.parametrize("paid,total", [("105998", "105998"), ("0", "0")])
    def test_nothing_paid_is_nothing_and_silent(self, paid, total, caplog) -> None:
        """The annulled Flex pack: 105998 - 105998."""
        with caplog.at_level(logging.WARNING, logger=envio_comprador.__name__):
            assert envio_comprador_bruto(Decimal(paid), Decimal(total), 1) is None
        assert caplog.text == ""

    @pytest.mark.parametrize(
        "paid,total",
        [
            (None, Decimal("100")),
            (Decimal("100"), None),
            (None, None),
            (Decimal("90"), Decimal("100")),  # negative difference
            (Decimal("NaN"), Decimal("100")),
            (Decimal("100"), Decimal("Infinity")),
            (float("nan"), 100.0),
            ("190", "100"),  # not a number type
            (True, Decimal("0")),
        ],
        ids=repr,
    )
    def test_unreadable_amounts_never_invent_base(self, paid, total, caplog) -> None:
        """Fail-closed (decision D4): add nothing and name the order."""
        with caplog.at_level(logging.WARNING, logger=envio_comprador.__name__):
            assert envio_comprador_bruto(paid, total, 777) is None
        assert "777" in caplog.text


class TestResolverOverTheCaptures:
    @pytest.mark.parametrize(
        "case,bruto,neto",
        [
            (FULFILLMENT_990, "990.00", "818.18"),
            (CROSS_DOCKING, "4699.09", "3883.55"),
            (FULFILLMENT_3990, "3990.00", "3297.52"),
            (SELF_SERVICE_4990, "4990.00", "4123.97"),
            (THREE_PAYMENTS, "5373.70", "4441.07"),
        ],
    )
    def test_every_logistic_type_counts(self, db, case, bruto, neto) -> None:
        """The buyer's shipping is income in EVERY mode (unlike the Flex
        bonificación, which is self_service only). The three payments of
        `THREE_PAYMENTS` do not triple it: it is read from the order."""
        seed_case(db, case)

        share = resolve_envio_comprador_by_order_ids(db, [case], IVA_ML_DIVISOR)[case]

        assert (share.bruto, share.neto) == (Decimal(bruto), Decimal(neto))

    def test_the_annulled_flex_pack_has_no_buyer_shipping(self, db) -> None:
        """`raw_costs.receiver.cost` says 2216.30, ML annulled it: the buyer
        paid nothing. MUTATION: reading `receiver.cost` adds 2216.30/1.21."""
        seed_case(db, SELF_SERVICE_PACK)
        assert db.query(MlOrdersOps.shipping_id).filter_by(order_id=SELF_SERVICE_PACK).scalar() is not None

        assert resolve_envio_comprador_by_order_ids(db, [SELF_SERVICE_PACK], IVA_ML_DIVISOR) == {}

    def test_it_does_not_need_a_shipment_row(self, db) -> None:
        """The money came in whether or not the cost payload has synced."""
        seed_case(db, FULFILLMENT_990, with_shipment=False)

        assert resolve_envio_comprador_by_order_ids(db, [FULFILLMENT_990], IVA_ML_DIVISOR)[FULFILLMENT_990].bruto == (
            Decimal("990.00")
        )

    def test_a_disagreeing_receiver_cost_is_logged_at_debug_and_the_difference_wins(self, db, caplog) -> None:
        seed_case(db, SELF_SERVICE_PACK)

        with caplog.at_level(logging.DEBUG, logger=envio_comprador.__name__):
            assert resolve_envio_comprador_by_order_ids(db, [SELF_SERVICE_PACK], IVA_ML_DIVISOR) == {}

        assert str(SELF_SERVICE_PACK) in caplog.text
        assert "receiver_cost" in caplog.text

    def test_a_null_amount_on_the_order_adds_nothing(self, db, caplog) -> None:
        seed_case(db, FULFILLMENT_990)
        order = db.query(MlOrdersOps).filter_by(order_id=FULFILLMENT_990).one()
        order.paid_amount = None
        db.commit()

        with caplog.at_level(logging.WARNING, logger=envio_comprador.__name__):
            assert resolve_envio_comprador_by_order_ids(db, [FULFILLMENT_990], IVA_ML_DIVISOR) == {}
        assert str(FULFILLMENT_990) in caplog.text

    def test_an_unknown_order_and_no_orders_are_absent(self, db) -> None:
        assert resolve_envio_comprador_by_order_ids(db, [], IVA_ML_DIVISOR) == {}
        assert resolve_envio_comprador_by_order_ids(db, [123], IVA_ML_DIVISOR) == {}


class TestPerOrderNotPerShipment:
    def test_two_orders_of_one_shipment_each_carry_their_own_money(self, db) -> None:
        """The bonificación is split per SHIPMENT; the buyer's shipping is per
        ORDER (each order carries its own `paid_amount - total_amount`), so
        nothing is split and nothing is counted twice. MUTATION: dividing by
        the orders sharing the `shipping_id` halves each."""
        sibling = CROSS_DOCKING + 1
        seed_case(db, CROSS_DOCKING)
        seed_case(db, CROSS_DOCKING, order_id=sibling, with_shipment=False)

        result = resolve_envio_comprador_by_order_ids(db, [CROSS_DOCKING, sibling], IVA_ML_DIVISOR)
        alone = resolve_envio_comprador_by_order_ids(db, [sibling], IVA_ML_DIVISOR)

        assert result[CROSS_DOCKING].bruto == result[sibling].bruto == Decimal("4699.09")
        assert alone[sibling] == result[sibling]


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

    def test_the_shipping_never_reduces_the_total_gauss_on_its_own(self, db) -> None:
        """The shipping IVA is informational: with 0% the Total Gauss is the
        same with and without the buyer's shipping line."""
        seed_case(db, FULFILLMENT_990)
        with_shipping = compute_order_metrics(db, [FULFILLMENT_990])[FULFILLMENT_990]
        order = db.query(MlOrdersOps).filter_by(order_id=FULFILLMENT_990).one()
        order.paid_amount = order.total_amount
        db.commit()
        without_shipping = compute_order_metrics(db, [FULFILLMENT_990])[FULFILLMENT_990]

        assert with_shipping.total_gauss == without_shipping.total_gauss
        assert with_shipping.neto_sin_iva == without_shipping.neto_sin_iva

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
        "case", [FULFILLMENT_990, CROSS_DOCKING, FULFILLMENT_3990, SELF_SERVICE_4990, SELF_SERVICE_PACK, THREE_PAYMENTS]
    )
    def test_the_base_and_the_visible_line_agree_on_every_capture(self, db, case) -> None:
        """Two readings of the same money (the order's `paid - total` for the
        base, the payments' `shipping_amount` for the line) must not drift."""
        seed_case(db, case)

        desc = descomponer_neto(db, [case])[case]
        resolved = resolve_envio_comprador_by_order_ids(db, [case], IVA_ML_DIVISOR)
        line_bruto = sum((c.bruto for c in desc.componentes if c.concepto == CONCEPTO_ENVIO_COMPRADOR), Decimal("0"))

        assert (resolved[case].bruto if case in resolved else Decimal("0")) == line_bruto

    def test_an_unresolved_goods_base_stays_unresolved_whatever_the_shipping(self, db) -> None:
        """The shipping can only add to a goods side we trust."""
        seed_case(db, FULFILLMENT_990)
        db.query(MlOrderItemCosto).filter_by(order_id=FULFILLMENT_990).delete()
        db.commit()

        desc = descomponer_neto(db, [FULFILLMENT_990])[FULFILLMENT_990]

        assert desc.base_venta_sin_iva is None
        assert desc.base_varios is None
