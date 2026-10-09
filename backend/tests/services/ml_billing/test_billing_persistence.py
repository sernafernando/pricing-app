"""ml-billing-balance PR 4c-i -- the persistence steps shared by the blocking pass and the worker lap.

`persist_details_page` and `persist_documents` were the inline body of `run_billing_sweep`; the
worker lap (PR 4c-ii) needs the same two steps without the blocking loop. The data is real: captured
2026-09-01 BILL sample rows and the period's captured documents.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from app.models.ml_billing import MlBillingCharge, MlBillingDocument
from app.services.ml_billing.billing_sweep_service import persist_details_page, persist_documents

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing"
_PERIOD = "2026-09-01"
ROWS = json.loads((_FIXTURES / "general_bill_2026_09_01_sample_rows.json").read_text())["rows"]
N = len(ROWS)
DOCUMENTS = json.loads((_FIXTURES / "documents_2026_09_01.json").read_text())


class TestPersistDetailsPage:
    def test_every_row_is_upserted_and_counted(self, db) -> None:
        assert persist_details_page(db, ROWS, _PERIOD, "BILL") == (N, N, 0)
        assert db.query(MlBillingCharge).filter_by(period_key=_PERIOD, document_type="BILL").count() == N

    def test_a_second_pass_over_the_same_page_adds_nothing(self, db) -> None:
        persist_details_page(db, ROWS, _PERIOD, "BILL")
        persist_details_page(db, ROWS, _PERIOD, "BILL")
        assert db.query(MlBillingCharge).count() == N

    def test_a_row_without_detail_id_is_counted_as_a_mapping_error_and_the_rest_still_stored(self, db) -> None:
        broken = copy.deepcopy(ROWS[0])
        del broken["charge_info"]["detail_id"]
        assert persist_details_page(db, [broken, *ROWS[1:]], _PERIOD, "BILL") == (N, N - 1, 1)
        assert db.query(MlBillingCharge).count() == N - 1

    def test_the_document_type_is_stored_on_the_rows(self, db) -> None:
        persist_details_page(db, ROWS, _PERIOD, "CREDIT_NOTE")
        assert {c.document_type for c in db.query(MlBillingCharge)} == {"CREDIT_NOTE"}


class TestPersistDocuments:
    def test_documents_are_upserted_with_their_count_and_reported_incomplete_without_rows(self, db) -> None:
        persisted = persist_documents(db, {"results": DOCUMENTS["BILL"]}, _PERIOD, "ML", "BILL")
        assert db.query(MlBillingDocument).count() == len(DOCUMENTS["BILL"]) == persisted.upserted
        assert persisted.count_details == sum(d["count_details"] for d in DOCUMENTS["BILL"])
        assert sorted(persisted.incomplete_ids) == sorted(str(d["id"]) for d in DOCUMENTS["BILL"])

    def test_the_documents_key_of_the_older_envelope_is_accepted_too(self, db) -> None:
        persisted = persist_documents(db, {"documents": DOCUMENTS["CREDIT_NOTE"]}, _PERIOD, "ML", "CREDIT_NOTE")
        assert persisted.upserted == len(DOCUMENTS["CREDIT_NOTE"])

    def test_an_empty_answer_persists_nothing(self, db) -> None:
        persisted = persist_documents(db, {"results": []}, _PERIOD, "ML", "BILL")
        assert (persisted.count_details, persisted.upserted, persisted.incomplete_ids) == (0, 0, [])
