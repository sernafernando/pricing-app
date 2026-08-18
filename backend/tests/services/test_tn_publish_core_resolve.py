"""Unit tests for the GBP-layer conversion stage (PC2/U1, PC3/U2,
design.md Decision 1's ordering constraint).

Ordering constraint under test throughout this file: conversion happens
INSIDE the GBP layer, BEFORE any precedence merge with stored overrides —
full precedence resolution lands in PR-5. If conversion ran AFTER
precedence, a stored override (already in kg/cm) would be divided by 1000 a
second time on re-publish.
"""

from datetime import date, timedelta

import pytest

from app.services.tn_publish_core.extract import Absent, extract_report_row
from app.services.tn_publish_core.resolve import (
    InvalidReportValueError,
    MissingExchangeRateError,
    Resolved,
    ResolvedDimensions,
    convert_weight_to_kg,
    map_dimensions,
    resolve_cost,
    resolve_field,
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


class TestUnparseableValueRaisesInvalidReportValueError:
    """Junk is NOT absence (S1's core distinction, restated in resolve.py's
    module docstring). A present KEY whose VALUE is non-numeric and
    non-blank (e.g. `weight = "N/A"`) is neither a real measurement nor
    GBP's "no data" convention (`Absent`) — it is a schema/data problem
    that must surface as a typed, field-and-value-naming error instead of
    an uncaught `ValueError` bubbling out of `float(...)`."""

    def test_convert_weight_to_kg_raises_on_non_numeric_junk(self):
        with pytest.raises(InvalidReportValueError) as exc_info:
            convert_weight_to_kg("N/A")

        assert exc_info.value.field_name == "weight"
        assert exc_info.value.raw_value == "N/A"
        assert "weight" in str(exc_info.value)
        assert "N/A" in str(exc_info.value)

    def test_map_dimensions_raises_naming_the_offending_field_and_value(self):
        with pytest.raises(InvalidReportValueError) as exc_info:
            map_dimensions(large_cm="not-a-number", wide_cm="2", height_cm="8")

        assert exc_info.value.field_name == "large"
        assert exc_info.value.raw_value == "not-a-number"
        assert "large" in str(exc_info.value)
        assert "not-a-number" in str(exc_info.value)


class TestPrecedenceLadder:
    """PC4/D2/D8 — `empty < profile < gbp < stored override < operator
    in-session edit`."""

    def test_stored_override_outranks_a_fresh_gbp_value(self):
        resolved = resolve_field(gbp_value=13.0, override_value=15.0, profile_value=Absent)
        assert resolved == Resolved(15.0, "override")

    def test_in_session_edit_outranks_the_stored_override(self):
        resolved = resolve_field(gbp_value=13.0, override_value=15.0, operator_value=20.0)
        assert resolved == Resolved(20.0, "operator")

    def test_profile_fills_a_gap_gbp_and_override_leave_empty(self):
        resolved = resolve_field(gbp_value=Absent, override_value=Absent, profile_value=30.0)
        assert resolved == Resolved(30.0, "profile")

    def test_full_ladder_empty_below_profile_below_gbp_below_override_below_operator(self):
        assert resolve_field() == Resolved(None, "empty")
        assert resolve_field(profile_value=30.0) == Resolved(30.0, "profile")
        assert resolve_field(profile_value=30.0, gbp_value=13.0) == Resolved(13.0, "gbp")
        assert resolve_field(profile_value=30.0, gbp_value=13.0, override_value=15.0) == Resolved(15.0, "override")
        assert resolve_field(profile_value=30.0, gbp_value=13.0, override_value=15.0, operator_value=20.0) == Resolved(
            20.0, "operator"
        )

    def test_none_at_a_layer_falls_through_like_absent(self):
        resolved = resolve_field(gbp_value=None, override_value=None, profile_value=30.0)
        assert resolved == Resolved(30.0, "profile")


class TestConvertThenResolveOverrideNotReDivided:
    """design Decision 1's ordering constraint, at the precedence-merge
    layer this time: a stored override is ALREADY in kg/cm/ARS — merging it
    via `resolve_field` must never re-run GBP-layer conversion on it."""

    def test_stored_weight_override_already_in_kg_is_not_re_divided_by_1000(self):
        gbp_weight_kg = convert_weight_to_kg("1000")  # -> 1.000 kg
        stored_override_kg = 2.5  # operator previously stored 2.5 kg, verbatim

        resolved = resolve_field(gbp_value=gbp_weight_kg, override_value=stored_override_kg)

        assert resolved.value == pytest.approx(2.5)
        assert resolved.source == "override"


class TestResolveCostD6:
    """PC8/D6 — ARS passes through; USD converts at today's
    `TipoCambio.venta` with fallback-to-latest; an empty `TipoCambio` table
    BLOCKS the cost field rather than sending unconverted USD as ARS."""

    def _seed_usd_rate(self, db, *, fecha, venta):
        from app.models.tipo_cambio import TipoCambio

        db.add(TipoCambio(fecha=fecha, moneda="USD", compra=venta, venta=venta))
        db.commit()

    def test_ars_cost_passes_through_unconverted(self, db):
        resolved = resolve_cost(db, "100.00", "ARS")
        assert resolved.value == pytest.approx(100.00)
        assert resolved.source == "gbp"

    def test_usd_cost_converts_at_todays_rate(self, db):
        self._seed_usd_rate(db, fecha=date.today(), venta=1000.0)

        resolved = resolve_cost(db, "100.00", "USD")

        assert resolved.value == pytest.approx(100000.0)
        assert resolved.source == "gbp"

    def test_usd_cost_falls_back_to_latest_rate_when_no_rate_today(self, db):
        self._seed_usd_rate(db, fecha=date.today() - timedelta(days=3), venta=900.0)

        resolved = resolve_cost(db, "100.00", "USD")

        assert resolved.value == pytest.approx(90000.0)

    def test_empty_tipo_cambio_table_blocks_the_cost_field(self, db):
        with pytest.raises(MissingExchangeRateError):
            resolve_cost(db, "100.00", "USD")

    def test_absent_cost_resolves_empty_not_a_rate_problem(self, db):
        resolved = resolve_cost(db, Absent, "USD")
        assert resolved == Resolved(None, "empty")
