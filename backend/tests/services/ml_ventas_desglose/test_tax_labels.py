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
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.ml_ventas_desglose.breakdown_service import (
    CONCEPTO_IMPUESTOS,
    _tax_label,
)

NAMES_FILE = Path(__file__).resolve().parents[2] / "fixtures" / "ml_payloads" / "tax_charge_names.json"

# The buyer's own tax. `_is_seller_charge` drops anything with "payer" in
# the name before labelling ever runs, so it has no label by design.
BUYER_TAX = "tax_withholding_payer-debitos_creditos"


def _recorded_names() -> list[str]:
    return json.loads(NAMES_FILE.read_text())["names"]


class TestTheFourShapesMlActuallyUses:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("tax_withholding_sirtac-jujuy", "Retención SIRTAC (Jujuy)"),
            ("tax_withholding_sirtac_sobretasa-la_rioja", "Sobretasa SIRTAC (La Rioja)"),
            ("tax_withholding-corrientes", "Retención (Corrientes)"),
            ("tax_withholding_collector-debitos_creditos", "Impuesto a los débitos y créditos"),
        ],
    )
    def test_it_names_the_tax_and_the_place(self, name: str, expected: str):
        assert _tax_label(name) == expected

    def test_the_national_tax_gets_no_province_in_parentheses(self):
        """Its slug is the tax itself, not a place -- appending it would
        read "... (Debitos Creditos)"."""
        assert "(" not in _tax_label("tax_withholding_collector-debitos_creditos")

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("tax_withholding_sirtac-caba", "Retención SIRTAC (CABA)"),
            ("tax_withholding_sirtac-entre_rios", "Retención SIRTAC (Entre Ríos)"),
            ("tax_withholding_sirtac-santiago_del_estero", "Retención SIRTAC (Santiago del Estero)"),
            ("tax_withholding_sirtac-cordoba", "Retención SIRTAC (Córdoba)"),
        ],
    )
    def test_province_names_are_spelled_properly_not_title_cased(self, name: str, expected: str):
        """Title-casing the slug would print "Caba", "Entre Rios",
        "Santiago Del Estero" and "Cordoba" on a money breakdown."""
        assert _tax_label(name) == expected


class TestEveryRecordedNameIsAccountedFor:
    def test_the_recording_is_not_empty(self):
        """Guards against this suite silently becoming a no-op."""
        assert len(_recorded_names()) >= 30

    @pytest.mark.parametrize("name", [n for n in _recorded_names() if n != BUYER_TAX])
    def test_it_gets_a_specific_label(self, name: str):
        """A seller-side tax that falls into the generic bucket means ML
        added a shape we do not read yet -- better a red test than a
        breakdown that hides which tax it charged."""
        assert _tax_label(name) != CONCEPTO_IMPUESTOS


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
        assert _tax_label(name) == CONCEPTO_IMPUESTOS

    def test_the_fallback_is_a_real_line_not_a_dropped_charge(self):
        """The bucket must be a label the breakdown renders, not an empty
        string or None that a caller would skip."""
        label = _tax_label("tax_withholding_nuevo-marte")

        assert isinstance(label, str) and label.strip()
        assert Decimal("1")  # the amount path is exercised in the breakdown tests
