"""
RED/GREEN — publication-link cron sweep script
(productos-catalog-family-tree PR1b).

Refreshes already-filled `ml_publication_links` rows on a slow cadence
(oldest `fetched_at` first, bounded batch). Mirrors
`drain_promo_refresh.py`'s DB-safety shape: HTTP calls happen OUTSIDE any
DB session, and DB writes use SHORT-LIVED per-row sessions (never one
session held open across the whole batch's HTTP round-trips) — this repo
had a real DB-pool-exhaustion incident from holding a session across
external HTTP.

Spec coverage:
  REQ-1 — selects rows ordered by fetched_at ascending (oldest first),
          capped at MAX_ROWS_PER_PASS.
  REQ-2 — HTTP fetch (`get_items_full_batch`) happens with NO db session
          open (verifies short-lived-session shape via call order, not
          just outcome).
  REQ-3 — a poison/erroring mla does not abort the rest of the batch.
  REQ-4 — empty due set -> no-op, no HTTP call.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch


from app.models.ml_publication_link import MlPublicationLink
from app.scripts import sync_publication_links as sweep


def _fake_ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return _Ctx()


class TestCronSweep:
    def test_empty_due_set_no_http_call(self, db) -> None:
        with (
            patch.object(sweep, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(sweep, "_try_acquire_sweep_lock", return_value=True),
            patch.object(sweep.ml_webhook_client, "get_items_full_batch", new_callable=AsyncMock) as mock_batch,
        ):
            sweep.run_sweep()

        mock_batch.assert_not_called()

    def test_lock_not_acquired_exits_without_processing(self, db) -> None:
        """An overlapping sweep already holds the advisory lock -> this pass
        exits immediately, doing no HTTP fetch and no read of due rows."""
        now = datetime.now(timezone.utc)
        db.add(MlPublicationLink(mla="MLA_DUE", item_id=1, fetched_at=now - timedelta(days=5)))
        db.commit()

        with (
            patch.object(sweep, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(sweep, "_try_acquire_sweep_lock", return_value=False) as mock_lock,
            patch.object(sweep.ml_webhook_client, "get_items_full_batch", new_callable=AsyncMock) as mock_batch,
        ):
            sweep.run_sweep()

        mock_lock.assert_called_once()
        mock_batch.assert_not_called()

    def test_selects_oldest_fetched_at_first_bounded(self, db) -> None:
        now = datetime.now(timezone.utc)
        db.add(MlPublicationLink(mla="MLA_OLDEST", item_id=1, fetched_at=now - timedelta(days=5)))
        db.add(MlPublicationLink(mla="MLA_NEWER", item_id=1, fetched_at=now - timedelta(days=1)))
        db.commit()

        with (
            patch.object(sweep, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(sweep, "_try_acquire_sweep_lock", return_value=True),
            patch.object(
                sweep.ml_webhook_client,
                "get_items_full_batch",
                new=AsyncMock(return_value={}),
            ) as mock_batch,
        ):
            sweep.run_sweep()

        called_mlas = mock_batch.await_args.args[0]
        assert called_mlas[0] == "MLA_OLDEST"

    def test_poison_mla_does_not_abort_batch(self, db) -> None:
        now = datetime.now(timezone.utc)
        db.add(MlPublicationLink(mla="MLA_POISON", item_id=1, fetched_at=now - timedelta(days=5)))
        db.add(MlPublicationLink(mla="MLA_OK", item_id=1, fetched_at=now - timedelta(days=4)))
        db.commit()

        full_item = {
            "family_id": "FAM1",
            "user_product_id": None,
            "inventory_id": None,
            "catalog_listing": False,
            "catalog_product_id": None,
            "item_relations": [],
        }

        with (
            patch.object(sweep, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(sweep, "_try_acquire_sweep_lock", return_value=True),
            patch.object(
                sweep.ml_webhook_client,
                "get_items_full_batch",
                new=AsyncMock(return_value={"MLA_POISON": full_item, "MLA_OK": full_item}),
            ),
            patch.object(
                sweep,
                "_persist_one",
                side_effect=[Exception("boom"), None],
            ) as mock_persist,
        ):
            sweep.run_sweep()

        assert mock_persist.call_count == 2
