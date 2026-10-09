"""ml-billing-balance PR 4b -- general CREDIT_NOTE ingestion (BS-6).

The data is the real 2026-09-01 capture: 196 credit-note rows
(`credit_note_2026_09.json.gz`), their 5 documents (`documents_2026_09_01.json`)
and the period's 33,210 BILL `detail_id`s (the BILL projection). Nothing is
hand-shaped. Credit-note rows are all `BONUS`, so the mapper stores them
negated; the sign -1 of `document_completeness` makes them equal ML's document
amounts, which is what these tests verify.
"""

from __future__ import annotations

import gzip
import json
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest

from app.core.config import settings
from app.models.ml_billing import MlBillingCharge, MlBillingDocument, MlBillingPeriodStat
from app.services.ml_billing import billing_sweep_service
from app.services.ml_billing.document_completeness import document_completeness
from app.services.ml_billing_ingestion.ingestion_service import upsert_billing_charge
from app.services.ml_billing_ingestion.mapper import map_billing_detail
from app.services.ml_orders_ingestion import sweep_service
from app.services.ml_webhook_client import ml_webhook_client

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing"
_PERIOD = "2026-09-01"
_EXPECTED_SUMS = {
    "5144645696": Decimal("6254513.00"),
    "5145502415": Decimal("375314.11"),
    "5148156085": Decimal("89463.11"),
    "5148156162": Decimal("27784.11"),
    "5224932860": Decimal("8675215.00"),
}


def _ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return lambda: _Ctx()


@pytest.fixture(autouse=True)
def _wiring(db, monkeypatch):
    monkeypatch.setattr(billing_sweep_service, "get_background_db", _ctx(db))
    monkeypatch.setattr(sweep_service, "get_background_db", _ctx(db))
    monkeypatch.setattr(settings, "ML_BILLING_ENABLED", True)
    monkeypatch.setattr(billing_sweep_service.time, "sleep", mock.Mock())


def _capture_pages() -> list[dict]:
    with gzip.open(_FIXTURES / "credit_note_2026_09.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)["pages"]


def _credit_note_documents() -> list[dict]:
    return json.loads((_FIXTURES / "documents_2026_09_01.json").read_text())["CREDIT_NOTE"]


def _bill_projection() -> list[list]:
    with gzip.open(_FIXTURES / "general_bill_2026_09_01_document_rows.json.gz", "rt") as fh:
        return json.load(fh)


def _sweep_credit_notes():
    details = mock.AsyncMock(side_effect=_capture_pages())
    documents = mock.AsyncMock(return_value={"results": _credit_note_documents()})
    periods = mock.AsyncMock(return_value={"results": [{"key": _PERIOD, "period_status": "OPEN"}]})
    with (
        mock.patch.object(ml_webhook_client, "get_billing_periods", new=periods),
        mock.patch.object(ml_webhook_client, "get_billing_details", new=details),
        mock.patch.object(ml_webhook_client, "get_billing_documents", new=documents),
    ):
        result = billing_sweep_service.run_billing_sweep(document_type="CREDIT_NOTE")
    return result, details, documents


def test_credit_note_rows_are_requested_as_credit_note_and_all_stored(db) -> None:
    result, details, documents = _sweep_credit_notes()

    assert result.error is None and result.stopped_early is False
    assert details.await_args_list[0].kwargs["document_type"] == "CREDIT_NOTE"
    documents.assert_awaited_once_with(_PERIOD, "ML", "CREDIT_NOTE")
    rows = db.query(MlBillingCharge).all()
    assert len(rows) == 196
    assert {(r.document_type, r.billing_source) for r in rows} == {("CREDIT_NOTE", "general")}


def test_documents_sum_to_ml_amounts_with_the_credit_note_sign(db) -> None:
    _sweep_credit_notes()

    completeness = document_completeness(db, _PERIOD, "CREDIT_NOTE")

    assert {c.document_id: c.stored_amount for c in completeness} == _EXPECTED_SUMS
    assert [c.stored_count for c in completeness] == [138, 45, 8, 4, 1]
    assert all(c.complete for c in completeness)


def test_the_single_whole_document_row_is_stored(db) -> None:
    _sweep_credit_notes()

    row = db.query(MlBillingCharge).filter_by(document_id="5224932860").one()
    assert (row.detail_sub_type, row.amount) == ("BS", Decimal("-8675215.00"))
    assert row.raw_detail["charge_info"]["charge_bonified_id"] is None


def test_cn_only_sub_types_are_stored(db) -> None:
    _sweep_credit_notes()

    stored = {s for (s,) in db.query(MlBillingCharge.detail_sub_type).distinct()}
    assert {"BIB", "BIBME", "BS"} <= stored


def test_the_link_to_the_original_charge_is_kept_even_without_a_local_target(db) -> None:
    captured = {
        str(r["charge_info"]["detail_id"]): r["charge_info"]["charge_bonified_id"]
        for r in _capture_pages()[0]["results"]
    }
    bill_ids = {str(row[0]) for row in _bill_projection()}

    _sweep_credit_notes()

    linked = {
        r.detail_id: r.raw_detail["charge_info"]["charge_bonified_id"]
        for r in db.query(MlBillingCharge).all()
        if r.raw_detail["charge_info"]["charge_bonified_id"] is not None
    }
    assert len(linked) == 195
    assert linked == {k: v for k, v in captured.items() if v is not None}
    # The originals are invoices of earlier periods: none is a BILL row of this one.
    assert not {str(v) for v in linked.values()} & bill_ids


def test_everything_ml_returned_is_persisted_pii_included(db) -> None:
    _sweep_credit_notes()

    raw = db.query(MlBillingCharge).filter_by(detail_id="69381860010").one().raw_detail
    assert raw["sales_info"][0]["payer_nickname"] == "ANANDIS"
    assert raw["sales_info"][0]["state_name"] == "CIUDAD AUTONOMA BUENOS AIRES"
    assert raw["marketplace_info"] == {"marketplace": "CORE"}
    assert raw["currency_info"] == {"currency_id": "ARS"}
    assert raw["charge_info"]["legal_document_number"] == "0058A00404299"


def test_ingestion_is_additive_and_leaves_bill_bonus_rows_alone(db) -> None:
    bill_bonus = [row for row in _bill_projection() if row[2] == "BONUS"]
    for detail_id, document_id, detail_type, amount in bill_bonus:
        raw = {
            "charge_info": {"detail_id": detail_id, "detail_type": detail_type, "detail_amount": amount},
            "document_info": {"document_id": document_id},
        }
        upsert_billing_charge(db, map_billing_detail(raw, _PERIOD, document_type="BILL"))
    db.commit()
    before = {r.detail_id: (r.amount, r.document_type) for r in db.query(MlBillingCharge).all()}
    assert len(before) == 1779

    _sweep_credit_notes()

    after = {r.detail_id: (r.amount, r.document_type) for r in db.query(MlBillingCharge).all()}
    assert len(after) == 1779 + 196
    assert {k: v for k, v in after.items() if v[1] == "BILL"} == before


def test_a_second_run_changes_nothing(db) -> None:
    _sweep_credit_notes()
    first = {r.detail_id: r.amount for r in db.query(MlBillingCharge).all()}

    _sweep_credit_notes()

    assert {r.detail_id: r.amount for r in db.query(MlBillingCharge).all()} == first
    assert db.query(MlBillingDocument).filter_by(document_type="CREDIT_NOTE").count() == 5


def test_a_credit_note_run_does_not_touch_the_bill_period_observation(db) -> None:
    _sweep_credit_notes()

    assert db.query(MlBillingPeriodStat).count() == 0


def test_the_bill_observation_does_not_count_credit_note_rows(db) -> None:
    _sweep_credit_notes()
    bill_page = {
        "results": [
            {
                "charge_info": {"detail_id": 70714313961, "detail_type": "CHARGE", "detail_amount": "100.00"},
                "document_info": {"document_id": "DOC1"},
            }
        ],
        "total": 1,
        "last_id": 70714313961,
    }
    end = {"results": [], "total": 0, "last_id": 0}
    periods = mock.AsyncMock(return_value={"results": [{"key": _PERIOD, "period_status": "OPEN"}]})
    with (
        mock.patch.object(ml_webhook_client, "get_billing_periods", new=periods),
        mock.patch.object(ml_webhook_client, "get_billing_details", new=mock.AsyncMock(side_effect=[bill_page, end])),
        mock.patch.object(ml_webhook_client, "get_billing_documents", new=mock.AsyncMock(return_value=None)),
    ):
        billing_sweep_service.run_billing_sweep()

    stat = db.query(MlBillingPeriodStat).filter_by(period_key=_PERIOD).one()
    assert stat.stored_total == 1
