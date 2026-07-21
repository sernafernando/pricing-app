"""
RED/GREEN — publication-link sync/lazy-fill service
(productos-catalog-family-tree PR1b).

`ml_publication_link_service.py` fetches full ML items (via
`ml_webhook_client.get_items_full_batch`) and UPSERTs the scalar snapshot
into `ml_publication_links` (by `mla`) plus REPLACES that mla's edges in
`ml_item_relations` (delete existing, re-insert the fresh set — an mla's
`item_relations` is a full set per refresh, not an accumulating log).

Spec coverage:
  REQ-1 — upserts a new `ml_publication_links` row for an mla with no
          existing row.
  REQ-2 — updates (not duplicates) an existing row, refreshing `fetched_at`.
  REQ-3 — replaces `ml_item_relations` edges for the mla (old edges gone,
          new edges present) — no partial-wipe if the new set is empty vs
          simply absent from the payload.
  REQ-4 — an mla the proxy returned nothing for is skipped entirely: no
          crash, existing row (if any) untouched, no partial wipe.
  REQ-5 — `get_stale_or_missing_mlas` returns mlas with no row or a row
          older than the freshness window; freshly-fetched rows are
          excluded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch


from app.models.ml_item_relation import MlItemRelation
from app.models.ml_publication_link import MlPublicationLink
from app.services import ml_publication_link_service as svc

FULL_ITEM = {
    "family_id": "FAM1",
    "user_product_id": "UP1",
    "inventory_id": "INV1",
    "catalog_listing": True,
    "catalog_product_id": "CP1",
    "item_relations": [{"id": "MLA_B", "stock_relation": 1}],
}

FULL_ITEM_NO_RELATIONS = {
    "family_id": None,
    "user_product_id": None,
    "inventory_id": None,
    "catalog_listing": False,
    "catalog_product_id": None,
    "item_relations": [],
}


class TestSyncPublicationLinks:
    def test_inserts_new_row_and_relations(self, db) -> None:
        with patch.object(
            svc.ml_webhook_client, "get_items_full_batch", new=AsyncMock(return_value={"MLA_A": FULL_ITEM})
        ):
            updated = svc.sync_publication_links(db, ["MLA_A"], item_id=42)
        db.commit()

        assert updated == 1
        row = db.query(MlPublicationLink).filter(MlPublicationLink.mla == "MLA_A").first()
        assert row is not None
        assert row.family_id == "FAM1"
        assert row.item_id == 42
        assert row.fetched_at is not None

        relations = db.query(MlItemRelation).filter(MlItemRelation.mla == "MLA_A").all()
        assert len(relations) == 1
        assert relations[0].related_mla == "MLA_B"
        assert relations[0].stock_relation == 1

    def test_updates_existing_row_refreshes_fetched_at(self, db) -> None:
        stale = datetime.now(timezone.utc) - timedelta(days=10)
        db.add(MlPublicationLink(mla="MLA_A", family_id="OLD", item_id=42, fetched_at=stale))
        db.commit()

        with patch.object(
            svc.ml_webhook_client, "get_items_full_batch", new=AsyncMock(return_value={"MLA_A": FULL_ITEM})
        ):
            svc.sync_publication_links(db, ["MLA_A"], item_id=42)
        db.commit()

        rows = db.query(MlPublicationLink).filter(MlPublicationLink.mla == "MLA_A").all()
        assert len(rows) == 1
        assert rows[0].family_id == "FAM1"
        # sqlite strips tzinfo on round-trip; compare naive wall-clock values.
        assert rows[0].fetched_at.replace(tzinfo=None) > stale.replace(tzinfo=None)

    def test_replaces_relations_old_edges_gone(self, db) -> None:
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_OLD", stock_relation=1))
        db.commit()

        with patch.object(
            svc.ml_webhook_client, "get_items_full_batch", new=AsyncMock(return_value={"MLA_A": FULL_ITEM})
        ):
            svc.sync_publication_links(db, ["MLA_A"], item_id=42)
        db.commit()

        relations = db.query(MlItemRelation).filter(MlItemRelation.mla == "MLA_A").all()
        assert [r.related_mla for r in relations] == ["MLA_B"]

    def test_duplicate_item_relations_deduped_no_integrity_error(self, db) -> None:
        """ML can list the same relation twice in one payload; the (mla,
        related_mla) unique constraint would otherwise raise IntegrityError and
        roll back the whole batch. replace_relations must dedup and keep one."""
        item_with_dupes = {
            **FULL_ITEM,
            "item_relations": [
                {"id": "MLA_B", "stock_relation": 1, "variation_id": None},
                {"id": "MLA_B", "stock_relation": 1, "variation_id": None},
            ],
        }

        with patch.object(
            svc.ml_webhook_client, "get_items_full_batch", new=AsyncMock(return_value={"MLA_A": item_with_dupes})
        ):
            svc.sync_publication_links(db, ["MLA_A"], item_id=42)
        db.commit()

        relations = db.query(MlItemRelation).filter(MlItemRelation.mla == "MLA_A").all()
        assert [r.related_mla for r in relations] == ["MLA_B"]

    def test_empty_item_relations_clears_existing_edges(self, db) -> None:
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_OLD", stock_relation=1))
        db.commit()

        with patch.object(
            svc.ml_webhook_client,
            "get_items_full_batch",
            new=AsyncMock(return_value={"MLA_A": FULL_ITEM_NO_RELATIONS}),
        ):
            svc.sync_publication_links(db, ["MLA_A"], item_id=42)
        db.commit()

        relations = db.query(MlItemRelation).filter(MlItemRelation.mla == "MLA_A").all()
        assert relations == []

    def test_proxy_returned_nothing_skips_no_crash_no_wipe(self, db) -> None:
        db.add(MlPublicationLink(mla="MLA_A", family_id="EXISTING", item_id=42, fetched_at=datetime.now(timezone.utc)))
        db.commit()

        with patch.object(svc.ml_webhook_client, "get_items_full_batch", new=AsyncMock(return_value={})):
            updated = svc.sync_publication_links(db, ["MLA_A"], item_id=42)
        db.commit()

        assert updated == 0
        row = db.query(MlPublicationLink).filter(MlPublicationLink.mla == "MLA_A").first()
        assert row.family_id == "EXISTING"

    def test_empty_mla_list_no_op(self, db) -> None:
        with patch.object(svc.ml_webhook_client, "get_items_full_batch", new=AsyncMock()) as mock_batch:
            updated = svc.sync_publication_links(db, [], item_id=42)

        assert updated == 0
        mock_batch.assert_not_called()


class TestGetStaleOrMissingMlas:
    def test_missing_mla_is_stale(self, db) -> None:
        result = svc.get_stale_or_missing_mlas(db, ["MLA_NEW"])
        assert result == ["MLA_NEW"]

    def test_old_row_is_stale(self, db) -> None:
        old = datetime.now(timezone.utc) - (svc.FRESHNESS_WINDOW + timedelta(hours=1))
        db.add(MlPublicationLink(mla="MLA_OLD", item_id=1, fetched_at=old))
        db.commit()

        assert svc.get_stale_or_missing_mlas(db, ["MLA_OLD"]) == ["MLA_OLD"]

    def test_fresh_row_is_excluded(self, db) -> None:
        fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.add(MlPublicationLink(mla="MLA_FRESH", item_id=1, fetched_at=fresh))
        db.commit()

        assert svc.get_stale_or_missing_mlas(db, ["MLA_FRESH"]) == []
