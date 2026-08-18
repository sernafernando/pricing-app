"""Unit tests for the GBP-layer conversion stage (PC2/U1, PC3/U2,
design.md Decision 1's ordering constraint).

Ordering constraint under test throughout this file: conversion happens
INSIDE the GBP layer, BEFORE any precedence merge with stored overrides —
full precedence resolution lands in PR-5. If conversion ran AFTER
precedence, a stored override (already in kg/cm) would be divided by 1000 a
second time on re-publish.
"""

import pytest

from app.services.tn_publish_core.extract import Absent, extract_report_row
from app.services.tn_publish_core.resolve import (
    ResolvedDimensions,
    convert_weight_to_kg,
    map_dimensions,
    resolve_gbp_fields,
)


class TestWeightGramsToKilogramsGolden:
    """PC2/U1 — verified 36/36 against the live store (engram
    architecture/tn-api-field-map, #1517): GBP reports weight in grams, TN
    wants kilograms."""

    @pytest.mark.parametrize(
        "grams,expected_kg",
        [
            ("1000", 1.000),
            ("250", 0.250),
        ],
    )
    def test_grams_to_kilograms_golden_conversion(self, grams, expected_kg):
        assert convert_weight_to_kg(grams) == pytest.approx(expected_kg)

    def test_absent_weight_passes_through_unconverted(self):
        assert convert_weight_to_kg(Absent) is Absent


class TestDimensionMappingLargeToWidthWideToDepthVerified36Of36LiveProducts:
    """PC3/U2 — THIS LOOKS LIKE A SWAP BUG. IT IS NOT.

    GBP `large` (largo) -> TN `width`; GBP `wide` (ancho) -> TN `depth`; GBP
    `height` (alto) -> TN `height` (no swap on that axis). Confirmed 36/36
    against the 535 already-published live products, zero exceptions,
    deterministic (engram discovery/tn-dim-mapping-swap, #1519). GBP has no
    profundidad/depth column of its own — `wide` is it. The rationale is
    stated in this test's name per the spec's explicit requirement, not
    only in a code comment (two independent, non-substitutable acceptance
    criteria)."""

    def test_dimension_mapping_large_to_width_wide_to_depth_verified_36_of_36_live_products(self):
        result = map_dimensions(large_cm="13", wide_cm="2", height_cm="8")

        assert isinstance(result, ResolvedDimensions)
        assert result.width == pytest.approx(13.0)
        assert result.depth == pytest.approx(2.0)
        assert result.height == pytest.approx(8.0)

    def test_absent_dimensions_pass_through_unconverted(self):
        result = map_dimensions(large_cm=Absent, wide_cm=Absent, height_cm=Absent)

        assert result.width is Absent
        assert result.depth is Absent
        assert result.height is Absent


class TestResolveGbpFieldsAppliesConversionBeforePrecedence:
    """Integration of extract -> resolve for the GBP source layer only (no
    precedence merge here — PR-5). Proves the ordering constraint: a raw
    report row is extracted then immediately converted, so anything reading
    `ResolvedGbpFields` already sees canonical kg/cm values."""

    def _row(self, **overrides) -> dict:
        row = {
            "weight": "1000.000000000",
            "wide": "2.000000000",
            "large": "13.000000000",
            "height": "8.000000000",
            "Marca": "ADATA",
            "Stock_Disponible": "5",
            "coslis_price": "100.00",
            "iclh_price": "95.00",
            "Moneda_Costo": "USD",
            "Código": "7791234567890",
            "tnr_lastPromotionalPrice": "45000.00",
        }
        row.update(overrides)
        return row

    def test_resolved_fields_carry_converted_weight_and_mapped_dimensions(self):
        extracted = extract_report_row(self._row())

        resolved = resolve_gbp_fields(extracted)

        assert resolved.weight_kg == pytest.approx(1.000)
        assert resolved.width_cm == pytest.approx(13.0)
        assert resolved.depth_cm == pytest.approx(2.0)
        assert resolved.height_cm == pytest.approx(8.0)

    def test_resolved_fields_pass_through_non_measurement_values_unchanged(self):
        extracted = extract_report_row(self._row())

        resolved = resolve_gbp_fields(extracted)

        assert resolved.marca == "ADATA"
        assert resolved.codigo == "7791234567890"
        assert resolved.coslis_price == "100.00"
        assert resolved.promotional_price == "45000.00"

    def test_resolved_absent_measurement_stays_absent_after_conversion(self):
        extracted = extract_report_row(self._row(weight="0.000000000"))

        resolved = resolve_gbp_fields(extracted)

        assert resolved.weight_kg is Absent
