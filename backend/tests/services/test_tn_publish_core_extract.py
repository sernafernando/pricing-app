"""Unit tests for strict report-78 extraction (PC1/S1, design.md Decision 1).

`parse_soap_response` (`app/api/endpoints/gbp_parser.py`) is schema-less — a
live ERP column rename (`higth` -> `height`, observed mid-investigation on
2026-08-14, see engram discovery/gbp-report-78-columns) silently produces
rows missing the renamed key. `extract_report_row` must raise, naming the
missing key, for every field this publisher depends on — never default to
0/None/"".
"""

import pytest

import app.services.tn_publish_core.extract as extract_module
from app.services.tn_publish_core.extract import (
    OPTIONAL_REPORT_FIELDS,
    REQUIRED_REPORT_FIELDS,
    Absent,
    ExtractedReportRow,
    MissingReportFieldError,
    _is_absent_value,
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

    def test_str_has_no_embedded_quotes(self):
        """Regression (pre-push code review, PR #1139): `MissingReportFieldError`
        inherits from `KeyError`, whose `__str__` returns `repr(args[0])` —
        wrapping the whole message in an extra pair of double quotes. That
        string is propagated verbatim into the `publish_fields_error` API
        field (D13) and would render literal quote characters to the
        operator. The other tests in this class assert with `in`, which is
        exactly why this slipped through — this test pins the EXACT
        rendered string instead of a substring."""
        exc = MissingReportFieldError("weight")

        assert str(exc) == "Report 78 row is missing required field 'weight'"
        assert not str(exc).startswith('"')
        assert not str(exc).endswith('"')


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


class TestOptionalTnFieldKeyEntirelyAbsent:
    """`tnr_lastPromotionalPrice` is a Tienda Nube field: GBP omits the key
    entirely for an item never published on TN, not just a blank value. A
    live probe of report-78 confirmed 0 of 335 actual publish-candidate
    rows (no `tnr_id`) carry this key at all. That absence is meaningful
    data ("not yet published on TN"), not a schema break, so it MUST
    degrade to `Absent` — exactly like a present-but-blank value — and
    MUST NOT raise `MissingReportFieldError`."""

    def test_tn_promo_price_is_optional_not_required(self):
        assert "tnr_lastPromotionalPrice" not in REQUIRED_REPORT_FIELDS
        assert "tnr_lastPromotionalPrice" in OPTIONAL_REPORT_FIELDS

    def test_publish_candidate_row_without_tn_promo_key_extracts_cleanly(self):
        """The real shape of a publish candidate: all 10 required keys
        present, `tnr_lastPromotionalPrice` key entirely absent from the
        row (not merely blank)."""
        row = _complete_row()
        del row["tnr_lastPromotionalPrice"]

        result = extract_report_row(row)

        assert isinstance(result, ExtractedReportRow)
        assert result.promotional_price is Absent

    def test_required_field_absence_still_raises_alongside_optional_field(self):
        """Guard against the fix silently degrading into "nothing is
        required": a REQUIRED key's absence must still raise even when an
        OPTIONAL key (`tnr_lastPromotionalPrice`) is also absent from the
        same row."""
        row = _complete_row()
        del row["weight"]
        del row["tnr_lastPromotionalPrice"]

        with pytest.raises(MissingReportFieldError) as exc_info:
            extract_report_row(row)

        assert exc_info.value.field_name == "weight"


class TestIsAbsentValueHandlesTypeErrorFromCoercion:
    """Pre-push code review of PR #1139: `_is_absent_value`'s `try/except`
    around `float(text)` only caught `ValueError`. Today that is safe
    because `text = str(raw).strip()` runs unconditionally before the
    `try` block, so `text` is always a `str` and `float(text)` cannot
    actually raise `TypeError` — but that safety is an IMPLICIT invariant
    of the current implementation, not a guarantee the function's
    signature makes. If the `str(...)` coercion is ever removed, a
    `TypeError` would escape uncaught into the caller. `resolve.py` already
    catches `(TypeError, ValueError)` for the equivalent conversion; this
    widens `_is_absent_value` to match."""

    def test_list_and_dict_raw_values_are_already_handled_via_value_error(self):
        """Baseline, not a regression test: `list`/`dict` raw values do NOT
        reach `TypeError` today. `str(raw)` converts them to a non-numeric
        string first, and `float(...)` on that string raises `ValueError`,
        already caught by the existing except clause. This is why those
        inputs (suggested as examples in the review) cannot be used to pin
        the `TypeError`-handling fix directly — this class's other test
        does that by simulating the coercion failure instead."""
        assert _is_absent_value([1, 2, 3]) is False
        assert _is_absent_value({"a": 1}) is False

    def test_type_error_from_float_coercion_is_handled_not_escaped(self, monkeypatch):
        """Pins the fix: widen the `except` in `_is_absent_value` to also
        catch `TypeError` from `float(text)`, matching `resolve.py`'s
        pattern. Simulated via monkeypatching `float` in the module's
        namespace, because — as documented on this class — no natural
        `raw` value reaches `float()` with a non-`str` `text` under the
        current implementation."""

        def _raising_float(_value):
            raise TypeError("simulated non-coercible value")

        monkeypatch.setattr(extract_module, "float", _raising_float, raising=False)

        assert _is_absent_value("not-actually-checked") is False
