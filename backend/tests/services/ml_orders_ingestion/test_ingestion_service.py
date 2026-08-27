"""Tests for the ML orders ingestion write path (slice 3).

Contract, not just behaviour (obs #1843 lesson): every test here asserts
what `upsert_order`'s docstring PROMISES -- fail-closed on a mapping error,
idempotent/guarded upsert, flag-gated writes -- not merely what the code
happens to do today.
"""

from __future__ import annotations


import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.services.ml_orders_ingestion.ingestion_service import (
    UpsertOutcome,
    upsert_order,
)


def _order_payload(
    order_id: int = 111,
    seller_id: int = 999,
    last_updated: str = "2026-08-20T10:00:00.000-04:00",
    status: str = "paid",
    item_id: str = "MLA1",
) -> dict:
    return {
        "id": order_id,
        "status": status,
        "date_created": "2026-08-19T10:00:00.000-04:00",
        "date_last_updated": last_updated,
        "seller": {"id": seller_id},
        "buyer": {"id": 55, "nickname": "comprador"},
        "total_amount": 100.0,
        "paid_amount": 100.0,
        "currency_id": "ARS",
        "order_items": [
            {
                "item": {"id": item_id, "seller_sku": "SKU-1", "title": "Producto"},
                "quantity": 1,
                "unit_price": 100.0,
            }
        ],
    }


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


class TestUpsertOrderFlagGate:
    def test_flag_off_writes_nothing(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        outcome = upsert_order(db, _order_payload())
        assert outcome == UpsertOutcome.DISABLED
        assert db.query(MlOrdersOps).count() == 0
        assert db.query(MlOrderItemOps).count() == 0


class TestUpsertOrderHappyPath:
    def test_creates_order_and_items(self, db):
        outcome = upsert_order(db, _order_payload())
        assert outcome == UpsertOutcome.OK

        row = db.query(MlOrdersOps).filter_by(order_id=111).one()
        assert row.status == "paid"
        assert row.seller_id == 999

        items = db.query(MlOrderItemOps).filter_by(order_id=111).all()
        assert len(items) == 1
        assert items[0].item_id == "MLA1"

    def test_never_raises_on_malformed_payload(self, db):
        """Fail-closed contract: a broken payload NEVER propagates an
        exception up to the caller (this is exactly the shape of the
        slice-2 mapper bug, obs #1843 -- the sweep must not die mid-window
        because one row is malformed)."""
        outcome = upsert_order(db, {"id": "not-an-int"})
        assert outcome == UpsertOutcome.MAPPING_ERROR
        assert db.query(MlOrdersOps).count() == 0


class TestUpsertOrderIdempotency:
    def test_same_payload_twice_is_a_structural_noop(self, db):
        """Re-ingesting the identical payload (same order_id, same
        ml_last_updated) must never duplicate the row or corrupt it -- the
        `ON CONFLICT ... WHERE excluded.ml_last_updated > stored` guard
        makes a genuinely identical re-ingest a no-op on the second call."""
        payload = _order_payload()
        first = upsert_order(db, payload)
        second = upsert_order(db, payload)

        assert first == UpsertOutcome.OK
        assert second == UpsertOutcome.SKIPPED_STALE
        assert db.query(MlOrdersOps).filter_by(order_id=111).count() == 1
        assert db.query(MlOrderItemOps).filter_by(order_id=111).count() == 1

    def test_newer_update_overwrites_stored_row(self, db):
        payload_v1 = _order_payload(status="paid", last_updated="2026-08-20T10:00:00.000-04:00")
        payload_v2 = _order_payload(status="cancelled", last_updated="2026-08-21T10:00:00.000-04:00")

        upsert_order(db, payload_v1)
        outcome = upsert_order(db, payload_v2)

        assert outcome == UpsertOutcome.OK
        row = db.query(MlOrdersOps).filter_by(order_id=111).one()
        assert row.status == "cancelled"
        assert db.query(MlOrdersOps).filter_by(order_id=111).count() == 1

    def test_stale_update_arriving_after_newer_is_discarded(self, db):
        """Out-of-order webhook/sweep race: an OLDER `date_last_updated`
        arriving after a NEWER one has already been stored must leave the
        stored row completely unchanged, and must be reported explicitly
        so the caller can log it rather than silently overwrite truth."""
        newer = _order_payload(status="paid", last_updated="2026-08-21T10:00:00.000-04:00")
        older = _order_payload(status="cancelled", last_updated="2026-08-20T10:00:00.000-04:00")

        upsert_order(db, newer)
        outcome = upsert_order(db, older)

        assert outcome == UpsertOutcome.SKIPPED_STALE
        row = db.query(MlOrdersOps).filter_by(order_id=111).one()
        assert row.status == "paid"  # unchanged -- the stale write never applied


class TestUpsertOrderNoDuplicateItems:
    def test_re_ingesting_a_newer_payload_does_not_duplicate_items(self, db):
        # variation_id is set (not None) here: the unique constraint on
        # (order_id, item_id, variation_id) is declared
        # `postgresql_nulls_not_distinct=True` so a NULL variation_id still
        # dedupes correctly on real Postgres, but SQLite (this test's
        # engine, see tests/conftest.py) has no equivalent for a NULL
        # column in a UNIQUE index -- same accepted gap as slice 1's model
        # tests (obs #1827, item 5: no live Postgres round-trip available
        # in this environment).
        v1 = _order_payload(last_updated="2026-08-20T10:00:00.000-04:00")
        v1["order_items"][0]["item"]["variation_id"] = 77
        v2 = _order_payload(last_updated="2026-08-21T10:00:00.000-04:00")
        v2["order_items"][0]["item"]["variation_id"] = 77
        upsert_order(db, v1)
        upsert_order(db, v2)

        assert db.query(MlOrderItemOps).filter_by(order_id=111, item_id="MLA1").count() == 1
