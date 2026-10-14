"""Publication-link service (productos-catalog-family-tree PR1b, reworked for the store).

Owns `ml_publication_links` (scalar snapshot, one row per `mla`) and
`ml_item_relations` (the item's `item_relations` edges, a full REPLACE per
refresh: an mla's relations are a complete set each time, not an accumulating
log, so stale edges must be deleted before the fresh set is inserted).

Two writers:
  - `sync_links_from_store` (the tree request): converges both tables to the
    ML publications store (`ml_items`), which ingests every publication
    continuously. LOCAL database reads only -- the tree request makes NO
    ml-webhook call. The old per-request `lazy_fill_links` was removed because
    it rendered one `get_item_full` per stale MLA sequentially (25-30 s on the
    first open of a 50-MLA product) and nothing else needed it.
  - `sync_publication_links` (cron sweep, `app/scripts/sync_publication_links.py`):
    fetches the full item through the proxy, kept for MLAs the store does not
    have yet.

DB-safety: the public functions expect an ALREADY-OPEN `Session`; the proxy
fetch in `sync_publication_links` happens BEFORE any DB write here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.ml_item_relation import MlItemRelation
from app.models.ml_publication_link import MlPublicationLink
from app.models.ml_publications import MlItem
from app.services.ml_webhook_client import ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)


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


_LinkFields = Tuple[Optional[str], Optional[str], Optional[str], bool, Optional[str]]
_Edge = Tuple[str, Optional[int], Optional[str]]


def _text_or_none(value) -> Optional[str]:
    return None if value is None else str(value)


def _store_edges(item_relations) -> List[_Edge]:
    """`(related_mla, stock_relation, variation_id)` in ML's order, deduped by related_mla --
    the same normalisation `replace_relations` applies on write."""
    edges: List[_Edge] = []
    seen: set = set()
    for relation in item_relations if isinstance(item_relations, list) else []:
        related_mla = relation.get("id") if isinstance(relation, dict) else None
        if not related_mla or related_mla in seen:
            continue
        seen.add(related_mla)
        edges.append((related_mla, relation.get("stock_relation"), _text_or_none(relation.get("variation_id"))))
    return edges


def sync_links_from_store(db: Session, mlas: List[str], item_id: int) -> int:
    """Converges `ml_publication_links` + `ml_item_relations` to the ML publications store.

    The tree reads those two tables; the store (`ml_items`) is their source of truth now:
    `family_id`, `user_product_id`, `inventory_id`, `catalog_listing` and `catalog_product_id`
    are typed columns, `item_relations` lives in the raw body. No ml-webhook call.

    Only MLAs with a stored body (`raw` and `fetched_at` set) are touched; a closed or gone item
    keeps its last body, so it still renders. An MLA the store has never fetched keeps whatever
    link rows it already has (fallback), or none (plain leaf) -- never an inline fetch. Rows are
    written only when they differ, so the steady state is two SELECTs and zero writes.

    Fail-open like the lazy-fill it replaces: any error is logged, the session rolled back, and
    0 returned -- the tree degrades to whatever is already persisted.

    Returns:
        Number of MLAs whose link row or edge set was written.
    """
    if not mlas:
        return 0
    try:
        store = {
            row.item_id: row
            for row in db.query(
                MlItem.item_id,
                MlItem.family_id,
                MlItem.user_product_id,
                MlItem.inventory_id,
                MlItem.catalog_listing,
                MlItem.catalog_product_id,
                MlItem.raw["item_relations"].label("item_relations"),
            ).filter(MlItem.item_id.in_(mlas), MlItem.raw.isnot(None), MlItem.fetched_at.isnot(None))
        }
        if not store:
            return 0

        links = {r.mla: r for r in db.query(MlPublicationLink).filter(MlPublicationLink.mla.in_(list(store)))}
        current_edges: Dict[str, List[_Edge]] = {}
        for edge in (
            db.query(MlItemRelation).filter(MlItemRelation.mla.in_(list(store))).order_by(MlItemRelation.id).all()
        ):
            current_edges.setdefault(edge.mla, []).append((edge.related_mla, edge.stock_relation, edge.variation_id))

        now = datetime.now(timezone.utc)
        written = 0
        for mla, row in store.items():
            fields = {
                "family_id": _text_or_none(row.family_id),
                "user_product_id": row.user_product_id,
                "inventory_id": row.inventory_id,
                "catalog_listing": bool(row.catalog_listing),
                "catalog_product_id": row.catalog_product_id,
            }
            link = links.get(mla)
            link_differs = (
                link is None
                or link.item_id != item_id
                or any(getattr(link, column) != value for column, value in fields.items())
            )
            edges = _store_edges(row.item_relations)
            edges_differ = current_edges.get(mla, []) != edges
            if not (link_differs or edges_differ):
                continue
            if link_differs:
                upsert_link(db, mla, fields, item_id, now)
            if edges_differ:
                replace_relations(
                    db, mla, [{"id": rel, "stock_relation": stock, "variation_id": var} for rel, stock, var in edges]
                )
            written += 1
        if written:
            db.commit()
        return written
    except Exception as exc:  # noqa: BLE001 -- fail-open: a convergence error must degrade the tree, never fail it
        logger.warning("sync_links_from_store: unavailable for item_id=%s: %s", item_id, exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0
