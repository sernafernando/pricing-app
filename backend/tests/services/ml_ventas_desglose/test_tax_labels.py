"""Labelling of `type='tax'` charges in the per-sale breakdown.

ML encodes WHICH tax and WHERE inside the charge name, so collapsing them
all into one "Impuestos" line throws that away: an operator looking at a
sale sees a number with no way to tell a SIRTAC withholding in Jujuy from
its provincial surcharge.

The names here are recorded from production, not invented -- a
hand-written fixture is a guess about ML's shape, and today a wrong guess
about exactly that cost this project a week of ingestion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from decimal import Decimal

from app.models.ml_payments import MlPaymentCharge
from app.services.ml_ventas_desglose.breakdown_service import (
    CONCEPTO_IMPUESTOS,
    debitos_creditos_total,
    is_debitos_creditos,
    is_recoverable_withholding,
    recoverable_withholding_total,
    tax_label,
    withholding_kind,
)


def _charge(name: str, type_: str, amount, refunded=None) -> MlPaymentCharge:
    return MlPaymentCharge(payment_id=0, name=name, type=type_, amount=amount, refunded=refunded)


# Deliberately NOT under `fixtures/ml_payloads/`: that directory is globbed
# by `test_mapper_against_recorded_payloads.py`, which hands every file in
# it to `map_order`. A list of charge names is not an order payload, and
# dropping it in there made that generic test try to map it -- green
# locally, red in CI.
NAMES_FILE = Path(__file__).resolve().parents[2] / "fixtures" / "ml_charges" / "tax_charge_names.json"

# The buyer's own tax. `is_seller_charge` drops anything with "payer" in
# the name before labelling ever runs, so it has no label by design.
BUYER_TAX = "tax_withholding_payer-debitos_creditos"


def _recorded_names() -> list[str]:
    return json.loads(NAMES_FILE.read_text(encoding="utf-8"))["names"]


class TestTheFourShapesMlActuallyUses:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("tax_withholding_sirtac-jujuy", "Retención IIBB (Jujuy) · SIRTAC"),
            ("tax_withholding_sirtac_sobretasa-la_rioja", "Retención IIBB por falta de alta (La Rioja)"),
            ("tax_withholding-corrientes", "Retención (Corrientes)"),
            ("tax_withholding_collector-debitos_creditos", "Impuesto a los débitos y créditos"),
        ],
    )
    def test_it_names_the_tax_and_the_place(self, name: str, expected: str):
        assert tax_label(name) == expected

    def test_the_national_tax_gets_no_province_in_parentheses(self):
        """Its slug is the tax itself, not a place -- appending it would
        read "... (Debitos Creditos)"."""
        assert "(" not in tax_label("tax_withholding_collector-debitos_creditos")

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("tax_withholding_sirtac-caba", "Retención IIBB (CABA) · SIRTAC"),
            ("tax_withholding_sirtac-entre_rios", "Retención IIBB (Entre Ríos) · SIRTAC"),
            ("tax_withholding_sirtac-santiago_del_estero", "Retención IIBB (Santiago del Estero) · SIRTAC"),
            ("tax_withholding_sirtac-cordoba", "Retención IIBB (Córdoba) · SIRTAC"),
        ],
    )
    def test_province_names_are_spelled_properly_not_title_cased(self, name: str, expected: str):
        """Title-casing the slug would print "Caba", "Entre Rios",
        "Santiago Del Estero" and "Cordoba" on a money breakdown."""
        assert tax_label(name) == expected


class TestEveryRecordedNameIsAccountedFor:
    def test_the_recording_is_where_this_test_says_it_is(self):
        """The file was MOVED out of `fixtures/ml_payloads/` because a
        generic test there hands every file to `map_order`. If it drifts
        back, or the path here goes stale, the parametrized test below
        collects zero cases and the suite goes green having checked
        nothing -- so the location is asserted, not assumed."""
        assert NAMES_FILE.is_file(), f"missing recording: {NAMES_FILE}"

    def test_the_recording_is_not_empty(self):
        """Guards against this suite silently becoming a no-op."""
        assert len(_recorded_names()) >= 30

    @pytest.mark.parametrize("name", [n for n in _recorded_names() if n != BUYER_TAX])
    def test_it_gets_a_specific_label(self, name: str):
        """A seller-side tax that falls into the generic bucket means ML
        added a shape we do not read yet -- better a red test than a
        breakdown that hides which tax it charged."""
        assert tax_label(name) != CONCEPTO_IMPUESTOS


class TestWithholdingKindClassifier:
    """`withholding_kind` is the ONE parser `tax_label` also uses (D1) -- so
    the label and the treatment (add-back, informational, subtracted) can
    never disagree. Every shape recorded from production is exercised."""

    @pytest.mark.parametrize("name", [n for n in _recorded_names() if "sirtac_sobretasa" not in n and "sirtac" in n])
    def test_sirtac_names_classify_as_sirtac(self, name: str):
        assert withholding_kind(name) == "sirtac"

    @pytest.mark.parametrize("name", [n for n in _recorded_names() if "sirtac_sobretasa" in n])
    def test_sobretasa_names_classify_as_sirtac_sobretasa(self, name: str):
        assert withholding_kind(name) == "sirtac_sobretasa"

    @pytest.mark.parametrize(
        "name",
        [n for n in _recorded_names() if "debitos_creditos" in n and n != "tax_withholding_payer-debitos_creditos"],
    )
    def test_collector_debitos_creditos_classifies_as_collector(self, name: str):
        assert withholding_kind(name) == "collector"

    def test_bare_provincial_withholding_classifies_as_generic(self):
        assert withholding_kind("tax_withholding-santa_fe") == ""

    def test_unrecognised_name_classifies_as_none(self):
        assert withholding_kind("algo_totalmente_distinto") is None
        assert withholding_kind(None) is None
        assert withholding_kind("") is None

    def test_a_fee_named_charge_typed_tax_is_not_a_withholding(self):
        """`withholding_kind` parses the NAME only -- a charge whose name is
        a known fee (never a `tax_withholding*` shape) is not a withholding
        regardless of what `type` it carries."""
        assert withholding_kind("meli_percentage_fee") is None

    def test_tax_label_output_is_unchanged_by_the_refactor(self):
        """Refactor proof: `tax_label` now calls `withholding_kind`
        internally, and every existing label must stay byte-identical."""
        assert tax_label("tax_withholding_sirtac-jujuy") == "Retención IIBB (Jujuy) · SIRTAC"
        assert tax_label("tax_withholding_sirtac_sobretasa-la_rioja") == "Retención IIBB por falta de alta (La Rioja)"
        assert tax_label("tax_withholding-corrientes") == "Retención (Corrientes)"
        assert tax_label("tax_withholding_collector-debitos_creditos") == "Impuesto a los débitos y créditos"


class TestRecoverableAndDebitosCreditosPredicates:
    """D1's two predicates on top of `withholding_kind`, plus the aggregate
    helpers -- both refund-aware via `net_amount`."""

    def test_sirtac_is_recoverable(self):
        assert is_recoverable_withholding("tax", "tax_withholding_sirtac-caba") is True

    def test_sobretasa_is_not_recoverable(self):
        assert is_recoverable_withholding("tax", "tax_withholding_sirtac_sobretasa-jujuy") is False

    def test_generic_retencion_is_not_recoverable(self):
        assert is_recoverable_withholding("tax", "tax_withholding-santa_fe") is False

    def test_collector_debitos_creditos_is_the_debitos_creditos_charge(self):
        assert is_debitos_creditos("tax", "tax_withholding_collector-debitos_creditos") is True

    def test_sirtac_is_not_the_debitos_creditos_charge(self):
        assert is_debitos_creditos("tax", "tax_withholding_sirtac-caba") is False

    def test_a_fee_named_charge_typed_tax_is_neither(self):
        assert is_recoverable_withholding("tax", "meli_percentage_fee") is False
        assert is_debitos_creditos("tax", "meli_percentage_fee") is False

    def test_recoverable_withholding_total_sums_net_of_refund(self):
        charges = [
            _charge("tax_withholding_sirtac-caba", "tax", Decimal("1792.23")),
            _charge("tax_withholding_sirtac-jujuy", "tax", Decimal("100.00"), refunded=Decimal("40.00")),
            _charge("tax_withholding_sirtac_sobretasa-jujuy", "tax", Decimal("500.00")),
            _charge("meli_percentage_fee", "fee", Decimal("74676.08")),
        ]
        assert recoverable_withholding_total(charges) == Decimal("1852.23")

    def test_debitos_creditos_total_sums_net_of_refund(self):
        charges = [
            _charge("tax_withholding_collector-debitos_creditos", "tax", Decimal("3584.45")),
            _charge("tax_withholding_sirtac-caba", "tax", Decimal("1792.23")),
        ]
        assert debitos_creditos_total(charges) == Decimal("3584.45")

    def test_no_matching_charges_totals_zero(self):
        assert recoverable_withholding_total([]) == Decimal("0")
        assert debitos_creditos_total([]) == Decimal("0")


class TestAnUnknownNameKeepsItsMoney:
    """Fail-open on LABELLING, never on the amount. A tax ML invents
    tomorrow must still appear as money the seller paid; dropping it
    because its name was unfamiliar would be a breakdown that quietly
    stops adding up."""

    @pytest.mark.parametrize(
        "name",
        [
            "tax_withholding_nuevo-marte",
            "tax_withholding_sirtac-provincia_que_no_existe",
            "algo_totalmente_distinto",
            "",
        ],
    )
    def test_it_falls_back_to_the_generic_bucket(self, name: str):
        assert tax_label(name) == CONCEPTO_IMPUESTOS

    def test_a_charge_with_no_name_at_all_still_lands_in_the_bucket(self):
        """`MlPaymentCharge.name` is nullable and a charge with a type and
        no name has been seen in production -- it is what made an earlier
        version discard whole payments. It must cost a label, never an
        amount."""
        assert tax_label(None) == CONCEPTO_IMPUESTOS

    def test_the_fallback_is_a_real_line_not_a_dropped_charge(self):
        """The bucket must be a label the breakdown renders, not an empty
        string or None that a caller would skip."""
        label = tax_label("tax_withholding_nuevo-marte")

        assert isinstance(label, str) and label.strip()


def test_an_unknown_but_well_formed_withholding_keeps_the_generic_label() -> None:
    """Pins pre-refactor behavior: before `withholding_kind` existed,
    `tax_label` already answered the generic bucket for a kind not in
    `_TAX_KINDS` (`if kind is None: return CONCEPTO_IMPUESTOS`). The
    refactor must not change that, and must not start claiming a kind."""
    from app.services.ml_ventas_desglose.breakdown_service import CONCEPTO_IMPUESTOS, tax_label, withholding_kind

    assert tax_label("tax_withholding_regimen_nuevo-caba") == CONCEPTO_IMPUESTOS
    assert withholding_kind("tax_withholding_regimen_nuevo-caba") is None
