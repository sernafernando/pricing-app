"""Unit tests for short-window CT mirror upsert (no GBP HTTP)."""

from __future__ import annotations

from uuid import uuid4

from app.models.commercial_transaction import CommercialTransaction
from app.services import ct_mirror_sync_service


def test_upsert_cts_from_records_inserts_and_updates(db):
    guid = uuid4()
    records = [
        {
            "ct_transaction": 55001,
            "ct_guid": str(guid),
            "comp_id": 1,
            "bra_id": 1,
            "supp_id": 7,
            "ct_docNumber": "FA-55001",
            "sd_id": 101,
            "ct_total": 100,
            "curr_id_transaction": 1,
            "ct_date": "2026-11-01T12:00:00",
            "ct_isCancelled": False,
        }
    ]
    assert ct_mirror_sync_service.upsert_cts_from_records(db, records) == [55001]
    row = db.query(CommercialTransaction).filter_by(ct_transaction=55001).one()
    assert row.ct_docNumber == "FA-55001"
    assert row.supp_id == 7

    records[0]["ct_docNumber"] = "FA-55001-B"
    records[0]["ct_total"] = 200
    assert ct_mirror_sync_service.upsert_cts_from_records(db, records) == [55001]
    db.refresh(row)
    assert row.ct_docNumber == "FA-55001-B"
    assert float(row.ct_total) == 200.0


def test_upsert_skips_rows_without_guid(db):
    assert (
        ct_mirror_sync_service.upsert_cts_from_records(
            db,
            [{"ct_transaction": 1, "ct_guid": None, "ct_docNumber": "X"}],
        )
        == []
    )
    assert db.query(CommercialTransaction).count() == 0
