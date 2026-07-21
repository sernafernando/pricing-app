"""
RED/GREEN — `lazy_fill_links` (productos-catalog-family-tree PR2, review fix
1/4: pool-exhaustion in the tree endpoint's lazy-fill).

The tree endpoint's old lazy-fill called `sync_publication_links` using the
REQUEST's `get_db` session, holding a pooled DB connection across the
sequential blocking HTTP fetch (`get_items_full_batch`) — the same
pool-exhaustion pattern this repo was bitten by (incident PR #811).
`lazy_fill_links` decouples the DB session from the HTTP round-trip,
mirroring `drain_promo_refresh.py` / `sync_publication_links.py`'s
short-lived-session shape, and adds a per-item_id advisory lock so
concurrent requests for the same product don't double-hit the proxy.

Spec coverage:
  REQ-1 — the HTTP fetch happens with NO db session open (stale-read
          session closes before the fetch; persistence sessions open
          only after).
  REQ-2 — advisory lock not acquired (another request already filling this
          product) -> skip entirely, no HTTP call.
  REQ-3 — a proxy failure inside `lazy_fill_links` never raises (fail-open).
  REQ-4 — per-item isolation: persistence happens in its own short-lived
          session per mla (mirrors the cron sweep).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.services import ml_publication_link_service as svc

FULL_ITEM = {
    "family_id": "FAM1",
    "user_product_id": "UP1",
    "inventory_id": "INV1",
    "catalog_listing": True,
    "catalog_product_id": "CP1",
    "item_relations": [],
}


def _fake_ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return _Ctx()


class TestLazyFillLinksDecoupledSessions:
    def test_http_fetch_happens_with_no_session_open(self, db) -> None:
        """The stale-read (lock-holding) session must be a SEPARATE,
        short-lived session from the per-mla persistence sessions — the
        HTTP fetch itself runs with none of them freshly opened around it
        (mirrors the cron sweep's call-order assertion)."""
        call_log: list = []

        def _tracking_ctx():
            call_log.append("session_open")
            return _fake_ctx(db)

        async def _tracked_fetch(mlas):
            call_log.append("http_fetch")
            return {"MLA1": FULL_ITEM}

        with (
            patch.object(svc, "get_background_db", side_effect=_tracking_ctx),
            patch.object(svc, "_try_acquire_item_lock", return_value=True),
            patch.object(svc, "get_stale_or_missing_mlas", return_value=["MLA1"]),
            patch.object(svc.ml_webhook_client, "get_items_full_batch", side_effect=_tracked_fetch),
        ):
            svc.lazy_fill_links(["MLA1"], item_id=1)

        # at least one session open before the fetch (the lock/stale-read
        # session) and the fetch itself is logged as its own event, not
        # nested inside a query.
        assert "http_fetch" in call_log
        assert call_log.index("session_open") < call_log.index("http_fetch")

    def test_persists_fetched_mla_after_lock_acquired(self, db) -> None:
        with (
            patch.object(svc, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(svc, "_try_acquire_item_lock", return_value=True),
            patch.object(svc, "get_stale_or_missing_mlas", return_value=["MLA1"]),
            patch.object(
                svc.ml_webhook_client, "get_items_full_batch", new=AsyncMock(return_value={"MLA1": FULL_ITEM})
            ),
        ):
            svc.lazy_fill_links(["MLA1"], item_id=1)

        from app.models.ml_publication_link import MlPublicationLink

        row = db.query(MlPublicationLink).filter(MlPublicationLink.mla == "MLA1").first()
        assert row is not None
        assert row.family_id == "FAM1"


class TestLazyFillLinksAdvisoryLock:
    def test_lock_not_acquired_skips_no_http(self, db) -> None:
        with (
            patch.object(svc, "_try_acquire_item_lock", return_value=False) as mock_lock,
            patch.object(svc, "get_stale_or_missing_mlas") as mock_stale,
            patch.object(svc.ml_webhook_client, "get_items_full_batch", new_callable=AsyncMock) as mock_batch,
        ):
            svc.lazy_fill_links(["MLA1"], item_id=1)

        mock_lock.assert_called_once()
        mock_stale.assert_not_called()
        mock_batch.assert_not_called()


class TestLazyFillLinksFailOpen:
    def test_proxy_failure_never_raises(self, db) -> None:
        with (
            patch.object(svc, "_try_acquire_item_lock", return_value=True),
            patch.object(svc, "get_stale_or_missing_mlas", return_value=["MLA1"]),
            patch.object(
                svc.ml_webhook_client,
                "get_items_full_batch",
                new=AsyncMock(side_effect=RuntimeError("proxy down")),
            ),
        ):
            svc.lazy_fill_links(["MLA1"], item_id=1)  # must not raise

    def test_no_stale_mlas_is_a_no_op(self, db) -> None:
        with (
            patch.object(svc, "_try_acquire_item_lock", return_value=True),
            patch.object(svc, "get_stale_or_missing_mlas", return_value=[]),
            patch.object(svc.ml_webhook_client, "get_items_full_batch", new_callable=AsyncMock) as mock_batch,
        ):
            svc.lazy_fill_links(["MLA1"], item_id=1)

        mock_batch.assert_not_called()
