"""RED/GREEN -- `descomponer_neto` (ml-ventas-modo-logistico, PR4, design D8-D12).

`neto` is untouched by this module: it stays whatever `compute_breakdown` /
`compute_neto_by_order_ids` already compute. This module only DECOMPOSES it
into IVA-free components -- see the design's own correction (D10): there is
no crediting step, no invariant that `total_gauss` stays put; the fee enters
the chain at its NET value, exactly like every other component.

Every reconciliation here is EXACT Decimal arithmetic -- no `pytest.approx`,
no float anywhere in `iva.py` or in these fixtures.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.services.ml_ventas_desglose.breakdown_service import (
    compute_breakdown,
    compute_neto_by_order_ids,
    tax_label,
)
from app.services.ml_ventas_desglose.iva import (
    CONCEPTO_CUPON_ML,
    CONCEPTO_ENVIO_COMPRADOR,
    CONCEPTO_IVA_NO_DETERMINADO,
    IVA_ML_DIVISOR,
    IVA_ML_PCT,
    RAZON_COSTO_SIN_ITEM,
    RAZON_ITEM_SIN_CANTIDAD,
    RAZON_ITEM_SIN_COSTO_CONGELADO,
    RAZON_VENTA_CON_DEVOLUCION,
    descomponer_neto,
)

_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ml_charges"


def _order(db, order_id: int) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            seller_id=999,
        )
    )


def _payment(
    db,
    payment_id: int,
    order_id: int,
    status: str = "approved",
    net_received_amount=None,
    shipping_amount=None,
    coupon_amount=None,
    transaction_amount_refunded=None,
) -> None:
    db.add(
        MlPaymentOps(
            payment_id=payment_id,
            order_id=order_id,
            status=status,
            net_received_amount=net_received_amount,
            shipping_amount=shipping_amount,
            coupon_amount=coupon_amount,
            transaction_amount_refunded=transaction_amount_refunded,
        )
    )


def _charge(db, payment_id: int, name: str, type_: str, amount, refunded=None) -> None:
    db.add(MlPaymentCharge(payment_id=payment_id, name=name, type=type_, amount=amount, refunded=refunded))


def _item_with_frozen_cost(
    db,
    order_id: int,
    item_id: str,
    precio_unitario: Decimal,
    iva_pct: Decimal,
    quantity: int = 1,
    variation_id=None,
) -> None:
    db.add(
        MlOrderItemOps(
            order_id=order_id,
            item_id=item_id,
            variation_id=variation_id,
            seller_sku="SKU-1",
            quantity=quantity,
            unit_price=precio_unitario,
        )
    )
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id=item_id,
            variation_id=variation_id,
            costo_origen=Decimal("50.00"),
            moneda="ARS",
            tipo_cambio=None,
            tipo_cambio_fecha=None,
            costo_unitario_ars=Decimal("50.00"),
            iva_pct=iva_pct,
            precio_unitario=precio_unitario,
            fuente="sku",
            producto_item_id=1,
        )
    )


class TestBasePlusIvaEqualsBrutoExactly:
    def test_every_component_reconstructs_its_own_bruto(self, db) -> None:
        order_id = 1
        _order(db, order_id)
        _payment(db, 1, order_id, net_received_amount=Decimal("867.59"))
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1050.00"), Decimal("10.5"))
        _charge(db, 1, "meli_percentage_fee", "fee", Decimal("100.00"))
        _charge(db, 1, "tax_withholding_sirtac-buenos_aires", "tax", Decimal("82.41"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert result.componentes  # something got decomposed
        for componente in result.componentes:
            assert componente.base + componente.iva == componente.bruto


class TestReconciliationIsExact:
    def test_reconciliation_sum_equals_neto_exactly(self, db) -> None:
        order_id = 2
        _order(db, order_id)
        _payment(db, 2, order_id, net_received_amount=Decimal("1000.00"))
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21.0"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert result.reconcilia is True
        assert result.diferencia == Decimal("0")
        # ZERO tolerance: this is not a `pytest.approx`; a mutation that adds
        # any tolerance to the reconciliation check must fail this test
        # against the mismatch case below, not this one.

    def test_a_one_cent_mismatch_never_reconciles(self, db) -> None:
        """The mismatch case a tolerance would swallow. If the production
        code is mutated to accept e.g. `abs(diferencia) <= Decimal("0.01")`,
        this test flips to `reconcilia=True` and fails -- that IS the
        mutation-verification for task 4.4."""
        order_id = 3
        _order(db, order_id)
        _payment(db, 3, order_id, net_received_amount=Decimal("100.01"))
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("100.00"), Decimal("21.0"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert result.reconcilia is False
        assert result.diferencia == Decimal("0.01")
        assert result.neto_sin_iva is None


class TestAnUnaccountableNetWithholdsTheTaxFreeNet:
    def test_a_net_that_does_not_close_yields_no_neto_sin_iva(self, db) -> None:
        """Production is known to hold one order (of 488) whose composition
        does not close -- see obs #1952/D12. This test does NOT reproduce
        it: the real payload has not been captured, and a hand-made cent of
        mismatch is not that order. It pins the CONSEQUENCE instead, which
        is what this module owes: a net nothing accounts for cannot be
        honestly de-IVA'd, so `neto_sin_iva` is withheld -- exactly like an
        unknown cost (D7) withholds Total Gauss.

        Naming a test after a production order it does not reproduce would
        claim a verification that never happened, which is the failure this
        whole module is built to avoid."""
        order_id = 777001
        _order(db, order_id)
        _payment(db, 4, order_id, net_received_amount=Decimal("19900.01"))
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("19900.00"), Decimal("21.0"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert result.reconcilia is False
        assert result.diferencia != Decimal("0")
        assert result.neto_sin_iva is None


class TestWithholdingTypeTaxNotSplit:
    def test_tax_withholding_carries_no_iva(self, db) -> None:
        order_id = 5
        _order(db, order_id)
        _payment(db, 5, order_id, net_received_amount=Decimal("-100.00"))
        _charge(db, 5, "tax_withholding_sirtac-buenos_aires", "tax", Decimal("100.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        withholding = next(
            c for c in result.componentes if c.concepto == tax_label("tax_withholding_sirtac-buenos_aires")
        )
        # The LABEL, never the raw ML slug: the operator reading this sees
        # "Cargo por vender" and "Envíos (Colecta)" beside it, not
        # `tax_withholding_sirtac-buenos_aires`.
        assert withholding.concepto != "tax_withholding_sirtac-buenos_aires"
        assert withholding.alicuota is None
        assert withholding.base == withholding.bruto
        assert withholding.iva == Decimal("0")


class TestWithholdingPredicateReusedNotDuplicated:
    def test_every_recorded_tax_name_is_recognised(self, db) -> None:
        """35 real `type='tax'` names (obs, captured 2026-09-10). Every one
        must land as an unsplit withholding component -- proving the
        `type == 'tax'` branch is reused, not a name allowlist."""
        names = json.loads((_FIXTURES_DIR / "tax_charge_names.json").read_text())["names"]
        # `tax_withholding_payer-debitos_creditos` is the BUYER's tax --
        # `is_seller_charge` drops it (contains "payer"), so it never
        # reduces `neto` even though it is recorded here (fixture's own
        # `__why__`).
        seller_names = [n for n in names if "payer" not in n]
        order_id = 6
        _order(db, order_id)
        neto = Decimal("0.00") - Decimal(len(seller_names)) * Decimal("10.00")
        _payment(db, 6, order_id, net_received_amount=neto)
        for name in names:
            _charge(db, 6, name, "tax", Decimal("10.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert result.reconcilia is True
        withholding_concepts = {c.concepto for c in result.componentes if c.alicuota is None}
        assert {tax_label(n) for n in seller_names} <= withholding_concepts

    def test_unknown_tax_name_never_recorded_still_recognised(self, db) -> None:
        """The mutation-verification: replacing `charge.type == 'tax'` with a
        hardcoded name list fails on a name that list has never seen."""
        order_id = 7
        _order(db, order_id)
        _payment(db, 7, order_id, net_received_amount=Decimal("-55.00"))
        _charge(db, 7, "tax_withholding_a_brand_new_province_ml_never_billed_before", "tax", Decimal("55.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert result.reconcilia is True
        withholding = result.componentes[0]
        assert withholding.alicuota is None
        # A province ML never billed before still gets a readable label
        # through the generic fallback, never the raw slug.
        assert withholding.concepto == tax_label("tax_withholding_a_brand_new_province_ml_never_billed_before")


class TestMixedRatePerItemDiscrimination:
    def test_two_rates_cannot_be_stripped_with_one(self, db) -> None:
        order_id = 8
        _order(db, order_id)
        _payment(db, 8, order_id, net_received_amount=Decimal("1500.00"))
        _item_with_frozen_cost(db, order_id, "MLA-21", Decimal("1000.00"), Decimal("21.0"))
        _item_with_frozen_cost(db, order_id, "MLA-10", Decimal("500.00"), Decimal("10.5"), variation_id=1)
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        naive = (Decimal("1500.00") / Decimal("1.21")).quantize(Decimal("0.01"))
        assert result.reconcilia is True
        assert result.neto_sin_iva != naive
        assert result.neto_sin_iva == Decimal("1278.94")  # 826.45 (21%) + 452.49 (10.5%)


class TestFreightStrippedAtFixed21Pct:
    def test_shipping_charge_always_splits_at_21(self, db) -> None:
        order_id = 9
        _order(db, order_id)
        _payment(db, 9, order_id, net_received_amount=Decimal("0.00"))
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21.0"))
        _charge(db, 9, "shp_cross_docking", "shipping", Decimal("1000.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        freight = next(c for c in result.componentes if c.concepto == "Envíos (Colecta)")
        assert freight.alicuota == IVA_ML_PCT
        assert freight.base == Decimal("-826.45")
        assert freight.iva == Decimal("-173.55")
        assert result.reconcilia is True

    def test_raw_gross_passthrough_would_change_neto_sin_iva(self, db) -> None:
        """Mutation-verification companion: a passthrough (no strip) of the
        freight charge would move `neto_sin_iva` by exactly the 173.55 of
        IVA this test pins as stripped away."""
        order_id = 10
        _order(db, order_id)
        _payment(db, 10, order_id, net_received_amount=Decimal("0.00"))
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21.0"))
        _charge(db, 10, "shp_cross_docking", "shipping", Decimal("1000.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        # Correct: item base (826.45) - freight base (826.45) == 0.00
        assert result.neto_sin_iva == Decimal("0.00")
        # A passthrough freight bruto (-1000.00 instead of -826.45) would
        # instead give item base - freight GROSS = 826.45 - 1000.00 = -173.55.
        assert result.neto_sin_iva != Decimal("-173.55")


class TestFeeEntersNetNotGross:
    def test_a_1000_fee_reduces_neto_sin_iva_by_82645_not_1000(self, db) -> None:
        order_a, order_b = 11, 12
        _order(db, order_a)
        _order(db, order_b)
        _payment(db, 11, order_a, net_received_amount=Decimal("5000.00"))
        _item_with_frozen_cost(db, order_a, "MLA1", Decimal("5000.00"), Decimal("21.0"))
        _payment(db, 12, order_b, net_received_amount=Decimal("4000.00"))
        _item_with_frozen_cost(db, order_b, "MLA1", Decimal("5000.00"), Decimal("21.0"))
        _charge(db, 12, "meli_percentage_fee", "fee", Decimal("1000.00"))
        db.commit()

        both = descomponer_neto(db, [order_a, order_b])
        result_a, result_b = both[order_a], both[order_b]
        netos = compute_neto_by_order_ids(db, [order_a, order_b])

        assert result_a.reconcilia is True
        assert result_b.reconcilia is True
        assert netos[order_a] - netos[order_b] == Decimal("1000.00")
        assert result_a.neto_sin_iva - result_b.neto_sin_iva == Decimal("826.45")


class TestChargeNetOfRefundNotRawAmount:
    def test_partially_refunded_fee_uses_its_net_amount(self, db) -> None:
        """Mutation-verification companion to task 4.10: a fee charge that
        was PARTIALLY refunded must enter the chain at `amount - refunded`
        (`net_amount`, reused from `breakdown_service`), never at the raw
        `amount`. Substituting the raw gross for the net changes both
        `neto` and `neto_sin_iva` here."""
        order_id = 15
        _order(db, order_id)
        _payment(db, 15, order_id, net_received_amount=Decimal("700.00"))
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21.0"))
        _charge(db, 15, "meli_percentage_fee", "fee", Decimal("500.00"), refunded=Decimal("200.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        fee = next(c for c in result.componentes if c.concepto == "Cargo por vender")
        assert fee.bruto == Decimal("-300.00")  # 500.00 - 200.00 refunded, never raw 500.00
        assert result.reconcilia is True


class TestNetoSinIvaDirection:
    def test_neto_sin_iva_higher_than_naive_uniform_21_strip(self, db) -> None:
        """Pins the counter-intuitive direction (D8/D10) so nobody 'fixes'
        it: an order with a lower-rate item (10.5) plus a 21%-stripped fee
        yields a `neto_sin_iva` ABOVE what uniformly stripping 21% off the
        whole net would give."""
        order_id = 13
        _order(db, order_id)
        _payment(db, 13, order_id, net_received_amount=Decimal("950.00"))
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1050.00"), Decimal("10.5"))
        _charge(db, 13, "meli_percentage_fee", "fee", Decimal("100.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]
        neto = compute_neto_by_order_ids(db, [order_id])[order_id]

        naive = neto / Decimal("1.21")
        assert result.reconcilia is True
        assert result.neto_sin_iva > naive


class TestUnrecognizedSellerChargeReportedNotDropped:
    def test_residual_charge_reports_iva_no_determinado(self, db) -> None:
        order_id = 14
        _order(db, order_id)
        _payment(db, 14, order_id, net_received_amount=Decimal("900.00"))
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21.0"))
        _charge(db, 14, "some_new_ml_charge_never_seen_before", "other", Decimal("100.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        residual = next(c for c in result.componentes if c.concepto == CONCEPTO_IVA_NO_DETERMINADO)
        assert residual.alicuota is None
        assert residual.bruto == Decimal("-100.00")
        assert result.reconcilia is True  # accounted for, not dropped


class TestDecimalOnly:
    def test_iva_ml_divisor_is_decimal(self) -> None:
        assert isinstance(IVA_ML_PCT, Decimal)
        assert isinstance(IVA_ML_DIVISOR, Decimal)
        assert IVA_ML_PCT == Decimal("21")
        assert IVA_ML_DIVISOR == Decimal("1.21")


class TestThePositiveSideIsNotOnlyTheItems:
    """`neto` comes from what the buyer PAID, and that is more than the
    goods. Decomposing only the items made every order where the buyer paid
    shipping -- or where ML funded part of a coupon -- fail to reconcile,
    and `neto_sin_iva` went silently None. The suite stayed green because
    no fixture ever set those columns: the arithmetic was never wrong on
    any case anyone had written down."""

    def test_buyer_paid_shipping_is_a_component(self, db) -> None:
        order_id = 900
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21"))
        _payment(db, 9001, order_id, net_received_amount=Decimal("1500.00"), shipping_amount=Decimal("500.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        envios = [c for c in result.componentes if c.concepto == CONCEPTO_ENVIO_COMPRADOR]
        assert len(envios) == 1
        assert envios[0].bruto == Decimal("500.00")
        assert envios[0].alicuota == IVA_ML_PCT
        assert result.reconcilia is True, f"no cerró por {result.diferencia}"
        assert result.neto_sin_iva is not None

    def test_ml_funded_coupon_is_a_component(self, db) -> None:
        order_id = 901
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21"))
        _payment(db, 9011, order_id, net_received_amount=Decimal("1200.00"), coupon_amount=Decimal("200.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        cupones = [c for c in result.componentes if c.concepto == CONCEPTO_CUPON_ML]
        assert len(cupones) == 1
        assert cupones[0].bruto == Decimal("200.00")
        assert result.reconcilia is True, f"no cerró por {result.diferencia}"

    def test_a_rejected_payments_shipping_never_enters(self, db) -> None:
        """`neto` is built from the relevant payments only. Reading shipping
        off every payment would inflate the positive side against a net that
        never saw that money."""
        order_id = 902
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21"))
        _payment(db, 9021, order_id, net_received_amount=Decimal("1000.00"))
        _payment(
            db, 9022, order_id, status="rejected", net_received_amount=Decimal("9999"), shipping_amount=Decimal("777")
        )
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert not [c for c in result.componentes if c.concepto == CONCEPTO_ENVIO_COMPRADOR]
        assert result.reconcilia is True


class TestWhatCannotBeSplitSaysSo:
    """An undeterminable split and a wrong sum look identical from the
    outside -- both leave `neto_sin_iva` empty. Naming the reason is what
    stops the reader hunting for an arithmetic bug that is not there."""

    def test_a_refunded_sale_names_the_reason(self, db) -> None:
        """Nothing we store says WHICH items came back, so the per-rate
        split of the goods is not determinable -- regardless of whether the
        totals happen to line up."""
        order_id = 903
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21"))
        _payment(
            db,
            9031,
            order_id,
            net_received_amount=Decimal("1000.00"),
            transaction_amount_refunded=Decimal("400.00"),
        )
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert RAZON_VENTA_CON_DEVOLUCION in result.razones
        assert result.neto_sin_iva is None

    def test_an_item_without_quantity_names_the_reason(self, db) -> None:
        order_id = 904
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21"))
        db.query(MlOrderItemOps).filter_by(order_id=order_id).update({"quantity": None})
        _payment(db, 9041, order_id, net_received_amount=Decimal("1000.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert RAZON_ITEM_SIN_CANTIDAD in result.razones
        assert result.neto_sin_iva is None


class TestAnOrderWithNoFrozenCostSaysSo:
    """PR3 freezes costs only for NEW ingestions, so historical orders have
    items and no frozen rows. The goods side then contributes nothing and
    the order stops reconciling -- which, unnamed, reads as an arithmetic
    bug in this module instead of the absent snapshot it actually is."""

    def test_a_PARTIALLY_frozen_order_names_the_reason_too(self, db) -> None:
        """Two items, one frozen. The goods side is short by one item and
        the sum stops closing -- and the first version of this check
        demanded ZERO frozen rows, so it stayed silent on exactly the case
        PR3's gradual rollout makes common."""
        order_id = 906
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21"))
        db.add(
            MlOrderItemOps(
                order_id=order_id,
                item_id="MLA2",
                variation_id=None,
                seller_sku="SKU-2",
                quantity=1,
                unit_price=Decimal("500.00"),
            )
        )
        _payment(db, 9061, order_id, net_received_amount=Decimal("1500.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert RAZON_ITEM_SIN_COSTO_CONGELADO in result.razones
        assert result.neto_sin_iva is None

    def test_items_without_frozen_costs_name_the_reason(self, db) -> None:
        order_id = 905
        db.add(
            MlOrderItemOps(
                order_id=order_id,
                item_id="MLA1",
                variation_id=None,
                seller_sku="SKU-1",
                quantity=1,
                unit_price=Decimal("1000.00"),
            )
        )
        _payment(db, 9051, order_id, net_received_amount=Decimal("1000.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert RAZON_ITEM_SIN_COSTO_CONGELADO in result.razones
        assert result.neto_sin_iva is None


class TestTheThirdPathToTheNetAgrees:
    """There are now THREE places that add a sale's net up:
    `compute_neto_by_order_ids` (the listing), `compute_breakdown` (the
    detail) and this module. The first two already have
    `TestTheTwoPathsToTheNetAgree` pinning them together, written because
    nothing forced them to match and an `in_mediation` bug once made them
    disagree. This module reuses the predicates but writes its OWN summing
    loop -- and the loop is exactly where that bug lived.

    So the third path gets the same pin: over the same orders, the
    components must add up to the listing's net."""

    def test_components_sum_to_the_listing_net(self, db) -> None:
        order_id = 910
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21"))
        _payment(db, 9101, order_id, net_received_amount=Decimal("1500.00"), shipping_amount=Decimal("700.00"))
        _charge(db, 9101, "sale_fee", "fee", Decimal("200.00"))
        db.commit()

        descomposicion = descomponer_neto(db, [order_id])[order_id]
        neto_listado = compute_neto_by_order_ids(db, [order_id])[order_id]

        assert neto_listado is not None
        assert sum((c.bruto for c in descomposicion.componentes), Decimal("0")) == neto_listado
        assert descomposicion.reconcilia is True

    def test_a_mediated_sale_agrees_too(self, db) -> None:
        """`in_mediation` is money COLLECTED, not money lost -- the bug that
        made the first two paths disagree. Pinned here as well so the third
        path cannot drift back into it."""
        order_id = 911
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21"))
        _payment(db, 9111, order_id, status="in_mediation", net_received_amount=Decimal("1000.00"))
        db.commit()

        descomposicion = descomponer_neto(db, [order_id])[order_id]
        neto_listado = compute_neto_by_order_ids(db, [order_id])[order_id]

        assert neto_listado == Decimal("1000.00")
        assert sum((c.bruto for c in descomposicion.componentes), Decimal("0")) == neto_listado


class TestBothModulesClassifyAChargeTheSameWay:
    """`compute_breakdown` reads the NAME first and `type == "tax"` second.
    This module used to do the opposite, so a charge typed `tax` whose name
    is a known fee would pass without IVA here and be labelled a commission
    there -- one charge, two treatments, which is exactly what
    `TestTheTwoPathsToTheNetAgree` exists to prevent."""

    def test_a_tax_typed_charge_with_a_fee_name_is_a_fee_in_both(self, db) -> None:
        order_id = 912
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21"))
        _payment(db, 9121, order_id, net_received_amount=Decimal("900.00"))
        # A known fee NAME carrying the `tax` TYPE -- the ambiguous shape.
        _charge(db, 9121, "meli_percentage_fee", "tax", Decimal("100.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]
        breakdown = compute_breakdown(db, [order_id])

        componente = next(c for c in result.componentes if c.bruto == Decimal("-100.00"))
        # Treated as a FEE: it carries ML's 21%, not passed through as a
        # withholding -- and it is labelled the same on both surfaces.
        assert componente.alicuota == IVA_ML_PCT
        assert componente.concepto in {line.concepto for line in breakdown.lines}


class TestAMissingItemRowIsNotAMissingQuantity:
    """`.get()` returns None both when the item row is gone and when it
    exists carrying a NULL quantity. Reporting the first as "item without
    quantity" names the opposite of what happened -- there is no item at
    all, there is a frozen cost left over from one."""

    def test_an_orphan_frozen_cost_names_its_own_reason(self, db) -> None:
        order_id = 913
        _item_with_frozen_cost(db, order_id, "MLA1", Decimal("1000.00"), Decimal("21"))
        # The item row disappears; its frozen cost deliberately survives
        # (see `congelar`'s docstring), leaving the cost orphaned.
        db.query(MlOrderItemOps).filter_by(order_id=order_id).delete()
        _payment(db, 9131, order_id, net_received_amount=Decimal("1000.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert RAZON_COSTO_SIN_ITEM in result.razones
        assert RAZON_ITEM_SIN_CANTIDAD not in result.razones
        assert result.neto_sin_iva is None
