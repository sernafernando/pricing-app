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
from app.services.ml_ventas_desglose.breakdown_service import compute_neto_by_order_ids
from app.services.ml_ventas_desglose.iva import (
    IVA_ML_DIVISOR,
    IVA_ML_PCT,
    CONCEPTO_IVA_NO_DETERMINADO,
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


def _payment(db, payment_id: int, order_id: int, status: str = "approved", net_received_amount=None) -> None:
    db.add(
        MlPaymentOps(
            payment_id=payment_id,
            order_id=order_id,
            status=status,
            net_received_amount=net_received_amount,
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


class TestReconciliationFailureOrder2000018322969636:
    def test_known_one_of_488_mismatch(self, db) -> None:
        """The one real order (of 488) whose composition does not close --
        see obs #1952/D12. `total_gauss` (PR5) is downstream of
        `neto_sin_iva`; withholding it here by leaving `neto_sin_iva=None`
        is what makes an unaccountable net impossible to honestly de-IVA,
        exactly like an unknown cost (D7) withholds Total Gauss."""
        order_id = 2000018322969636
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

        withholding = next(c for c in result.componentes if c.concepto == "tax_withholding_sirtac-buenos_aires")
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
        # `_is_seller_charge` drops it (contains "payer"), so it never
        # reduces `neto` even though it is recorded here (fixture's own
        # `__why__`).
        seller_names = [n for n in names if "payer" not in n]
        order_id = 6
        _order(db, order_id)
        neto = Decimal("0.00") - Decimal(len(seller_names)) * Decimal("10.00")
        _payment(db, 6, order_id, net_received_amount=neto)
        for i, name in enumerate(names):
            _charge(db, 6, name, "tax", Decimal("10.00"))
        db.commit()

        result = descomponer_neto(db, [order_id])[order_id]

        assert result.reconcilia is True
        withholding_concepts = {c.concepto for c in result.componentes if c.alicuota is None}
        assert set(seller_names) <= withholding_concepts

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
        assert withholding.concepto == "tax_withholding_a_brand_new_province_ml_never_billed_before"


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
        (`_net_amount`, reused from `breakdown_service`), never at the raw
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
