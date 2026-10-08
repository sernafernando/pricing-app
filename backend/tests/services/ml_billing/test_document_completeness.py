"""ml-billing-balance PR 2b -- per-document completeness is a QUERY (BS-3, BD-3).

The data is the real 2026-09-01 capture. `general_bill_2026_09_01_document_rows`
holds the 33,210 rows the sweep got (26,020 for document 5140824542 and 7,190
for 5140811928), which is the "silent row loss" scenario: ML's documents say
26,056 / 534,258,231.37 and 7,204 / 56,674,709.86. The COMPLETE scenario adds
the 36 + 14 rows ML never returned, synthesized as the exact difference (see
the fixtures README).

SQLite is the CI session here: it sums `Numeric` as float, so amounts are
compared at cent precision, which is how the function reports them.
"""

from __future__ import annotations

import gzip
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import inspect, insert

from app.models.ml_billing import MlBillingCharge, MlBillingDocument
from app.services.ml_billing.document_completeness import document_completeness
from app.services.ml_billing_ingestion.ingestion_service import upsert_billing_document
from app.services.ml_billing_ingestion.mapper import map_billing_document

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing"
_PERIOD = "2026-09-01"
_BILL_A, _BILL_B = "5140824542", "5140811928"


def _documents() -> dict:
    return json.loads((_FIXTURES / "documents_2026_09_01.json").read_text())


def _store_documents(db, document_type: str) -> None:
    for raw in _documents()[document_type]:
        upsert_billing_document(db, map_billing_document(raw, _PERIOD, "ML"))
    db.commit()


def _captured_rows() -> list[dict]:
    """The 33,210 real rows, amounts signed the way the mapper stores them
    (BONUS negated)."""
    with gzip.open(_FIXTURES / "general_bill_2026_09_01_document_rows.json.gz", "rt") as fh:
        projected = json.load(fh)
    rows = []
    for detail_id, document_id, detail_type, amount in projected:
        value = Decimal(str(amount))
        rows.append(
            {
                "detail_id": str(detail_id),
                "period_key": _PERIOD,
                "document_id": str(document_id),
                "document_type": "BILL",
                "detail_type": detail_type,
                "amount": -value if detail_type == "BONUS" else value,
            }
        )
    return rows


def _store_rows(db, rows: list[dict]) -> None:
    db.execute(insert(MlBillingCharge.__table__), rows)
    db.commit()


def _missing_rows() -> list[dict]:
    """The 36 + 14 rows ML never returned: synthesized so each document's sum
    is exactly ML's total."""
    rows = []
    for document_id, count, difference in ((_BILL_A, 36, "966809.54"), (_BILL_B, 14, "116243.45")):
        share = (Decimal(difference) / count).quantize(Decimal("0.01"))
        amounts = [share] * (count - 1)
        amounts.append(Decimal(difference) - sum(amounts))
        for index, amount in enumerate(amounts):
            rows.append(
                {
                    "detail_id": f"9{document_id}{index:02d}",
                    "period_key": _PERIOD,
                    "document_id": document_id,
                    "document_type": "BILL",
                    "detail_type": "CHARGE",
                    "amount": amount,
                }
            )
    return rows


def _by_document(results) -> dict:
    return {r.document_id: r for r in results}


class TestBillCompleteness:
    def test_the_silent_row_loss_is_reported_incomplete_for_both_documents(self, db) -> None:
        _store_documents(db, "BILL")
        _store_rows(db, _captured_rows())

        by_document = _by_document(document_completeness(db, _PERIOD, "BILL"))

        a, b = by_document[_BILL_A], by_document[_BILL_B]
        assert (a.stored_count, a.stored_amount) == (26020, Decimal("533291421.83"))
        assert (b.stored_count, b.stored_amount) == (7190, Decimal("56558466.41"))
        assert (a.expected_count, a.expected_amount) == (26056, Decimal("534258231.37"))
        assert (b.expected_count, b.expected_amount) == (7204, Decimal("56674709.86"))
        assert a.complete is False
        assert b.complete is False
        assert a.stored_count + b.stored_count == 33210

    def test_the_whole_period_is_complete_once_every_row_is_stored(self, db) -> None:
        _store_documents(db, "BILL")
        _store_rows(db, _captured_rows() + _missing_rows())

        by_document = _by_document(document_completeness(db, _PERIOD, "BILL"))

        a, b = by_document[_BILL_A], by_document[_BILL_B]
        assert (a.stored_count, a.stored_amount) == (26056, Decimal("534258231.37"))
        assert (b.stored_count, b.stored_amount) == (7204, Decimal("56674709.86"))
        assert a.complete is True
        assert b.complete is True
        assert a.stored_count + b.stored_count == 33260

    def test_a_right_count_with_a_wrong_sum_is_incomplete(self, db) -> None:
        _store_documents(db, "BILL")
        rows = _captured_rows() + _missing_rows()
        rows[-1] = {**rows[-1], "amount": rows[-1]["amount"] + Decimal("0.01")}
        _store_rows(db, rows)

        by_document = _by_document(document_completeness(db, _PERIOD, "BILL"))

        assert by_document[_BILL_A].complete is True
        assert by_document[_BILL_B].stored_count == 7204
        assert by_document[_BILL_B].complete is False

    def test_a_right_sum_with_a_wrong_count_is_incomplete(self, db) -> None:
        _store_documents(db, "BILL")
        rows = _captured_rows() + _missing_rows()
        # Two rows that cancel each other out: the count moves, the sum does not.
        rows += [
            {**rows[0], "detail_id": "8000000001", "amount": Decimal("5.00")},
            {**rows[0], "detail_id": "8000000002", "amount": Decimal("-5.00")},
        ]
        _store_rows(db, rows)

        a = _by_document(document_completeness(db, _PERIOD, "BILL"))[_BILL_A]

        assert a.stored_amount == a.expected_amount
        assert a.stored_count == a.expected_count + 2
        assert a.complete is False

    def test_a_document_with_no_stored_rows_is_incomplete_not_missing(self, db) -> None:
        _store_documents(db, "BILL")

        by_document = _by_document(document_completeness(db, _PERIOD, "BILL"))

        assert set(by_document) == {_BILL_A, _BILL_B}
        assert by_document[_BILL_A].stored_count == 0
        assert by_document[_BILL_A].stored_amount == Decimal("0.00")
        assert by_document[_BILL_A].complete is False


class TestScope:
    def test_only_the_asked_period_and_type(self, db) -> None:
        _store_documents(db, "BILL")
        _store_documents(db, "CREDIT_NOTE")
        other_period = map_billing_document(_documents()["BILL"][0] | {"id": 1}, "2026-08-01", "ML")
        upsert_billing_document(db, other_period)
        db.commit()

        bills = document_completeness(db, _PERIOD, "BILL")
        credit_notes = document_completeness(db, _PERIOD, "CREDIT_NOTE")

        assert {r.document_id for r in bills} == {_BILL_A, _BILL_B}
        assert len(credit_notes) == 5
        assert document_completeness(db, "2026-07-01", "BILL") == []

    def test_unknown_document_type_is_rejected(self, db) -> None:
        with pytest.raises(ValueError):
            document_completeness(db, _PERIOD, "INVOICE")


class TestCreditNoteSign:
    def test_credit_note_rows_are_counted_with_sign_minus_one(self, db) -> None:
        """Design D10: BILL sign +1, CREDIT_NOTE sign -1. The sign is the
        design's assumption; PR 4b verifies it against the captured CN rows
        (the 196-row 2026-09-01 set, document sums 6,254,513.00 / ...). This
        test only pins that the function applies it."""
        _store_documents(db, "CREDIT_NOTE")
        _store_rows(
            db,
            [
                {
                    "detail_id": "7000000001",
                    "period_key": _PERIOD,
                    "document_id": "5224932860",
                    "document_type": "CREDIT_NOTE",
                    "detail_type": "BONUS",
                    "amount": Decimal("-8675215.00"),
                }
            ],
        )

        result = _by_document(document_completeness(db, _PERIOD, "CREDIT_NOTE"))["5224932860"]

        assert (result.expected_count, result.stored_count) == (1, 1)
        assert result.stored_amount == Decimal("8675215.00")
        assert result.complete is True


class TestNothingIsStored:
    def test_the_documents_table_has_no_aggregate_columns_and_the_query_writes_nothing(self, db) -> None:
        _store_documents(db, "BILL")
        before = [
            tuple(r)
            for r in db.query(MlBillingDocument.document_id, MlBillingDocument.amount, MlBillingDocument.count_details)
            .order_by(MlBillingDocument.document_id)
            .all()
        ]

        document_completeness(db, _PERIOD, "BILL")
        db.commit()

        after = [
            tuple(r)
            for r in db.query(MlBillingDocument.document_id, MlBillingDocument.amount, MlBillingDocument.count_details)
            .order_by(MlBillingDocument.document_id)
            .all()
        ]
        assert before == after
        columns = {c["name"] for c in inspect(db.bind).get_columns("ml_billing_documents")}
        assert columns.isdisjoint({"stored_count", "stored_sum", "complete", "checked_at"})
