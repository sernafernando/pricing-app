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


def test_fetch_window_truncates_keeping_newest_by_ct_date(monkeypatch):
    # Oldest first in payload; after cap we must keep the newest dates.
    oversized = [
        {
            "ct_transaction": i,
            "ct_guid": str(i),
            "ct_date": f"2026-11-{(i % 28) + 1:02d}T12:00:00",
        }
        for i in range(5001)
    ]
    # Force a clearly newest row at the end of the unsorted payload.
    oversized.append(
        {
            "ct_transaction": 99999,
            "ct_guid": "newest",
            "ct_date": "2026-12-31T23:59:59",
        }
    )

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return oversized

    class _Client:
        def __init__(self, *a, **k):
            self.timeout = k.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return _Resp()

    captured: dict = {}

    def _client_factory(*a, **k):
        client = _Client(*a, **k)
        captured["timeout"] = k.get("timeout")
        return client

    monkeypatch.setattr(ct_mirror_sync_service.httpx, "Client", _client_factory)
    rows = ct_mirror_sync_service._fetch_window(days=2, timeout_s=20.0)
    assert len(rows) == ct_mirror_sync_service.MAX_FETCH_ROWS
    assert rows[0]["ct_transaction"] == 99999
    assert captured["timeout"] is not None
    assert float(captured["timeout"].connect) == 5.0
    assert float(captured["timeout"].read) == 20.0
