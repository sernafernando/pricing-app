"""Unit tests for strict report-78 extraction (PC1/S1, design.md Decision 1).

`parse_soap_response` (`app/api/endpoints/gbp_parser.py`) is schema-less — a
live ERP column rename (`higth` -> `height`, observed mid-investigation on
2026-08-14, see engram discovery/gbp-report-78-columns) silently produces
rows missing the renamed key. `extract_report_row` must raise, naming the
missing key, for every field this publisher depends on — never default to
0/None/"".
"""

import pytest

from app.services.tn_publish_core.extract import (
    REQUIRED_REPORT_FIELDS,
    Absent,
    ExtractedReportRow,
    MissingReportFieldError,
    extract_report_row,
)


def _complete_row(**overrides) -> dict:
    """A report-78 row carrying every key `extract_report_row` depends on,
    with plausible non-empty values — the "nothing renamed, nothing blank"
    baseline. Individual keys/values are overridden per test."""
    row = {
        "weight": "1000.000000000",
        "wide": "13.000000000",
        "large": "2.000000000",
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


class TestMissingKeyRaises:
    """PC1/S1 — a missing report-78 KEY (not merely a blank value) MUST
    raise, naming the exact field. This is the schema-rename failure mode:
    `row.get(key, 0)` would silently succeed with a garbage `0`."""

    @pytest.mark.parametrize("missing_key", REQUIRED_REPORT_FIELDS)
    def test_missing_key_raises_naming_the_field(self, missing_key):
        row = _complete_row()
        del row[missing_key]

        with pytest.raises(MissingReportFieldError) as exc_info:
            extract_report_row(row)

        assert exc_info.value.field_name == missing_key
        assert missing_key in str(exc_info.value)

    def test_height_renamed_to_higth_raises_naming_height(self):
        """The exact real-world scenario from engram
        discovery/gbp-report-78-columns: the ERP renamed `height` -> `higth`
        live. `extract_report_row` must not silently treat that as
        `height` being absent-with-zero; it must raise naming `height`."""
        row = _complete_row()
        row["higth"] = row.pop("height")

        with pytest.raises(MissingReportFieldError) as exc_info:
            extract_report_row(row)

        assert exc_info.value.field_name == "height"


class TestCompleteRowExtractsCleanly:
    """PC1 — a row with every key present extracts to a typed projection
    with nothing defaulted."""

    def test_complete_row_returns_typed_projection(self):
        row = _complete_row()

        result = extract_report_row(row)

        assert isinstance(result, ExtractedReportRow)
        assert result.marca == "ADATA"
        assert result.stock_disponible == "5"
        assert result.coslis_price == "100.00"
        assert result.iclh_price == "95.00"
        assert result.moneda_costo == "USD"
        assert result.codigo == "7791234567890"
        assert result.promotional_price == "45000.00"
        assert result.weight_grams == "1000.000000000"
        assert result.wide_cm == "13.000000000"
        assert result.large_cm == "2.000000000"
        assert result.height_cm == "8.000000000"


class TestAbsentVsZero:
    """design.md Decision 1's "Absent vs zero" table — measurement fields
    and promotional_price report `Absent` (never `0`/`None`) when GBP is
    silent, because a zero-dimension/zero-promo product does not exist."""

    @pytest.mark.parametrize("blank_value", ["0.000000000", "", "0"])
    @pytest.mark.parametrize("field", ["weight", "wide", "large", "height"])
    def test_blank_measurement_returns_absent_sentinel(self, field, blank_value):
        row = _complete_row(**{field: blank_value})

        result = extract_report_row(row)

        attr_name = {
            "weight": "weight_grams",
            "wide": "wide_cm",
            "large": "large_cm",
            "height": "height_cm",
        }[field]
        assert getattr(result, attr_name) is Absent

    def test_blank_promotional_price_returns_absent_sentinel(self):
        row = _complete_row(**{"tnr_lastPromotionalPrice": "0.000000000"})

        result = extract_report_row(row)

        assert result.promotional_price is Absent

    def test_absent_is_never_none_and_never_zero(self):
        assert Absent is not None
        assert Absent != 0
        assert Absent != ""
        assert bool(Absent) is False

    def test_nonzero_measurement_is_not_absent(self):
        row = _complete_row(height="8.000000000")

        result = extract_report_row(row)

        assert result.height_cm is not Absent
        assert result.height_cm == "8.000000000"
