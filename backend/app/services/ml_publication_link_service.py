"""Publication-link sync/backfill service (productos-catalog-family-tree PR1b).

Fetches the FULL ML item (via `MLWebhookClient.get_items_full_batch`,
`/render`) for a set of MLAs and persists the link fields into
`ml_publication_links` (scalar snapshot, UPSERT by `mla`) plus the item's
`item_relations` into `ml_item_relations` (a full REPLACE per refresh — an
mla's item_relations is a complete set each time ML reports it, not an
accumulating log, so stale edges must be deleted before the fresh set is
inserted).

Used by two callers (both outside this module's scope for PR1b):
  - Lazy-fill: PR2's tree endpoint calls `sync_publication_links` for a
    product's MLAs when the tree is expanded, filling missing/stale rows
    on demand.
  - Cron sweep: `app/scripts/sync_publication_links.py` calls this on a
    slow cadence to keep already-filled rows fresh.

Graceful degradation: `get_items_full_batch` never raises and simply
omits any MLA the proxy couldn't serve — this service mirrors that by
skipping such MLAs entirely (no crash, no partial wipe of existing data).

DB-safety: this module's public functions expect an ALREADY-OPEN
`Session` and do the HTTP fetch (`get_items_full_batch`) BEFORE any DB
writes here — callers that batch across many MLAs (the cron sweep) must
keep the HTTP round-trip outside any DB session per this repo's
pool-exhaustion lesson (see `app/scripts/drain_promo_refresh.py`); this
service itself performs only the (fast) DB upsert step.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models.ml_item_relation import MlItemRelation
from app.models.ml_publication_link import MlPublicationLink
from app.services.ml_webhook_client import ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

# How long a fetched row is considered fresh before it's due for refresh.
# Hybrid backfill design: lazy-fill on view + this cadence for the cron sweep.
FRESHNESS_WINDOW = timedelta(hours=6)


def get_stale_or_missing_mlas(db: Session, mlas: List[str]) -> List[str]:
    """Returns the subset of `mlas` that have no `ml_publication_links` row
    yet, or whose row is older than `FRESHNESS_WINDOW`.

    Args:
        db: Open SQLAlchemy session.
        mlas: Candidate MLA ids to check.

    Returns:
        The subset needing a (re)fetch, in the same relative order as
        `mlas`. Empty input -> empty output.
    """
    if not mlas:
        return []

    now = datetime.now(timezone.utc)
    threshold = now - FRESHNESS_WINDOW

    existing_rows = db.query(MlPublicationLink).filter(MlPublicationLink.mla.in_(mlas)).all()
    fetched_at_by_mla: Dict[str, datetime] = {}
    for row in existing_rows:
        fetched_at_by_mla[row.mla] = row.fetched_at

    stale_or_missing: List[str] = []
    for mla in mlas:
        fetched_at = fetched_at_by_mla.get(mla)
        if fetched_at is None:
            stale_or_missing.append(mla)
            continue

        # sqlite (tests) strips tzinfo on round-trip; Postgres (prod) keeps it.
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)

        if fetched_at < threshold:
            stale_or_missing.append(mla)

    return stale_or_missing


def sync_publication_links(db: Session, mlas: List[str], item_id: int) -> int:
    """Fetches full item data for `mlas` and UPSERTs `ml_publication_links`
    + REPLACES `ml_item_relations` edges per mla.

    Args:
        db: Open SQLAlchemy session (caller commits — this function does
            NOT commit, so it can be composed into a larger transaction
            or a per-row short-lived session, per caller's needs).
        mlas: MLA ids to (re)fetch and persist.
        item_id: The ERP `item_id` these MLAs belong to (stored on the
            link row for the tree assembly's join path).

    Returns:
        Number of MLAs actually persisted (proxy-served ones). MLAs the
        proxy returned nothing for are skipped and NOT counted.
    """
    if not mlas:
        return 0

    fetched = resolve_maybe_async(ml_webhook_client.get_items_full_batch(mlas))
    if not fetched:
        return 0

    now = datetime.now(timezone.utc)
    persisted = 0

    for mla, item_data in fetched.items():
        upsert_link(db, mla, item_data, item_id, now)
        replace_relations(db, mla, item_data.get("item_relations") or [])
        persisted += 1

    return persisted


def upsert_link(db: Session, mla: str, item_data: Dict, item_id: int, fetched_at: datetime) -> None:
    """Inserts or updates the scalar `ml_publication_links` row for `mla`."""
    row = db.query(MlPublicationLink).filter(MlPublicationLink.mla == mla).first()

    if row is None:
        row = MlPublicationLink(mla=mla)
        db.add(row)

    row.family_id = item_data.get("family_id")
    row.user_product_id = item_data.get("user_product_id")
    row.inventory_id = item_data.get("inventory_id")
    row.catalog_listing = bool(item_data.get("catalog_listing") or False)
    row.catalog_product_id = item_data.get("catalog_product_id")
    row.item_id = item_id
    row.fetched_at = fetched_at


def replace_relations(db: Session, mla: str, item_relations: List[Dict]) -> None:
    """Deletes all existing `ml_item_relations` edges for `mla` and
    re-inserts the fresh set — `item_relations` is a full snapshot per ML
    refresh, not an accumulating log, so stale edges must not linger."""
    db.query(MlItemRelation).filter(MlItemRelation.mla == mla).delete(synchronize_session=False)

    # Dedup by related_mla: ML can list the same relation twice in one payload,
    # and the (mla, related_mla) unique constraint would raise IntegrityError on
    # the second insert — which, on the shared-session lazy-fill path, would roll
    # back every other MLA's good work in the same batch. Keep the first.
    seen: set = set()
    for relation in item_relations:
        related_mla = relation.get("id")
        if not related_mla or related_mla in seen:
            continue
        seen.add(related_mla)
        db.add(
            MlItemRelation(
                mla=mla,
                related_mla=related_mla,
                stock_relation=relation.get("stock_relation"),
                variation_id=relation.get("variation_id"),
            )
        )
