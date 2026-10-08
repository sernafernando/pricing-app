"""ml-billing-balance PR 2b -- billing document mapping (BD-1, BD-2) and the
document/legal fields on the charge DTO.

Fixtures are the real documents of period 2026-09-01
(`tests/fixtures/ml_billing/documents_2026_09_01.json`, copied from
`billing_balance_capture_20261007_123428.json.gz`) and the real sample rows.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.ml_billing_ingestion.mapper import (
    MappingError,
    map_billing_detail,
    map_billing_document,
    parse_legal_reference,
)

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing"


def _documents() -> dict:
    return json.loads((_FIXTURES / "documents_2026_09_01.json").read_text())


def _bill(document_id: int) -> dict:
    return next(d for d in _documents()["BILL"] if d["id"] == document_id)


class TestParseLegalReference:
    def test_real_references(self) -> None:
        assert parse_legal_reference("0058A00975220") == (58, "A", 975220)
        assert parse_legal_reference("0001A03750426") == (1, "A", 3750426)

    @pytest.mark.parametrize("malformed", ["", "58A975220", "0058A0097522", "0058a00975220", "0058A009752201", None, 5])
    def test_malformed_parses_to_nulls_without_failing(self, malformed) -> None:
        assert parse_legal_reference(malformed) == (None, None, None)


class TestMapBillingDocument:
    def test_bill_keeps_ml_values_only(self) -> None:
        dto = map_billing_document(_bill(5140824542), "2026-09-01", "ML")

        assert not isinstance(dto, MappingError)
        assert dto.document_id == "5140824542"
        assert (dto.group, dto.document_type, dto.period_key) == ("ML", "BILL", "2026-09-01")
        assert dto.amount == Decimal("534258231.37")
        assert dto.unpaid_amount == Decimal("0.0")
        assert dto.count_details == 26056
        assert dto.document_status == "BILLED"
        assert dto.currency_id == "ARS"
        assert dto.expiration_date == date(2026, 9, 22)
        assert dto.associated_document_id is None

    def test_reference_number_is_kept_and_parsed(self) -> None:
        dto = map_billing_document(_bill(5140824542), "2026-09-01", "ML")

        assert dto.reference_number == "0058A00975220"
        assert (dto.legal_point_of_sale, dto.legal_letter, dto.legal_number) == (58, "A", 975220)
        assert dto.files == [{"file_id": "3272435881", "reference_number": "0058A00975220"}]

    def test_raw_is_an_unmodified_deep_copy(self) -> None:
        raw = _bill(5140811928)
        dto = map_billing_document(raw, "2026-09-01", "ML")

        assert dto.raw == raw
        assert dto.raw is not raw

    def test_credit_note_keeps_the_association_to_an_earlier_invoice(self) -> None:
        cn = next(d for d in _documents()["CREDIT_NOTE"] if d["id"] == 5224932860)
        dto = map_billing_document(cn, "2026-09-01", "ML")

        assert dto.document_type == "CREDIT_NOTE"
        assert dto.associated_document_id == "5032752366"
        assert dto.amount == Decimal("8675215.0")

    def test_malformed_reference_is_stored_with_null_parts(self) -> None:
        raw = _bill(5140824542)
        raw["files"] = [{"file_id": "1", "reference_number": "NO-ES-UNA-REFERENCIA"}]
        dto = map_billing_document(raw, "2026-09-01", "ML")

        assert not isinstance(dto, MappingError)
        assert dto.reference_number == "NO-ES-UNA-REFERENCIA"
        assert (dto.legal_point_of_sale, dto.legal_letter, dto.legal_number) == (None, None, None)

    def test_no_files_is_not_an_error(self) -> None:
        raw = _bill(5140824542)
        raw["files"] = []
        dto = map_billing_document(raw, "2026-09-01", "ML")

        assert not isinstance(dto, MappingError)
        assert dto.reference_number is None

    def test_missing_id_or_bad_amount_fails_closed(self) -> None:
        no_id = _bill(5140824542)
        no_id.pop("id")
        bad_amount = _bill(5140824542)
        bad_amount["amount"] = "N/A"

        no_type = _bill(5140824542)
        no_type.pop("document_type")

        for raw in (no_id, no_type, bad_amount, ["no soy dict"]):
            result = map_billing_document(raw, "2026-09-01", "ML")
            assert isinstance(result, MappingError)


class TestChargeCarriesDocumentAndLegalFields:
    def _row(self) -> dict:
        return json.loads((_FIXTURES / "general_bill_2026_09_01_sample_rows.json").read_text())["rows"][0]

    def test_legal_fields_come_from_charge_info(self) -> None:
        dto = map_billing_detail(self._row(), "2026-09-01")

        assert dto.legal_document_number == "0058A00975220"
        assert dto.legal_document_status == "PROCESSED"

    def test_document_type_is_the_fetched_type_and_defaults_to_bill(self) -> None:
        assert map_billing_detail(self._row(), "2026-09-01").document_type == "BILL"
        assert map_billing_detail(self._row(), "2026-09-01", document_type="CREDIT_NOTE").document_type == "CREDIT_NOTE"

    def test_a_document_still_processing_has_no_number_yet(self) -> None:
        row = self._row()
        row["charge_info"]["legal_document_number"] = None
        row["charge_info"]["legal_document_status"] = "PROCESSING"
        dto = map_billing_detail(row, "2026-09-01")

        assert dto.legal_document_number is None
        assert dto.legal_document_status == "PROCESSING"
