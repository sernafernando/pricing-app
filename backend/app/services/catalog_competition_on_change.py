"""Queue a catalog-competition snapshot refresh when the store records a change of an active catalog listing.

The owner's rule (2026-11-16): the catalog-competition ranking is refreshed every time Mercado Libre tells us the
publication changed. The store already turns those notifications into change-log rows, so the trigger is the row,
not the raw notification: only a REAL change of the item, its prices, its sale price or its buy-box competition
counts (most `items` notifications change nothing). Promotions are left to hay_mejores, which has its own enqueue.

Called from `store._log_change`, inside the store's transaction, in a SAVEPOINT: a queue problem never costs the
change-log row or its events.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_catalog_competition import MLCatalogCompetition
from app.models.ml_publications import MlChangeLog, MlItem
from app.services import catalog_competition_refresh_queue as queue

logger = logging.getLogger(__name__)

TRIGGER_RESOURCES = frozenset({"item", "prices", "sale_price", "competition"})
TRIGGER_KINDS = frozenset({"change", "restored"})
ACTIVE = "active"


def enqueue_after_change(db: Session, entry: MlChangeLog, now: Optional[datetime] = None) -> bool:
    """Queue `entry`'s item for a snapshot refresh when the rule applies; True when it was queued."""
    if entry.item_id is None or entry.resource_type not in TRIGGER_RESOURCES or entry.kind not in TRIGGER_KINDS:
        return False
    now = now if now is not None else datetime.now(timezone.utc)
    try:
        with db.begin_nested():
            item = db.query(MlItem.catalog_listing, MlItem.status).filter(MlItem.item_id == entry.item_id).one_or_none()
            if item is None or item.catalog_listing is not True or item.status != ACTIVE:
                return False
            if _consulted_within_gap(db, entry.item_id, now):
                return False
            due_at = now + timedelta(seconds=settings.ML_PUB_CATALOG_COMPETITION_CHANGE_DEBOUNCE_SECONDS)
            queue.enqueue_debounced(db, [(entry.item_id, due_at)])
            return True
    except Exception:  # noqa: BLE001 — the change-log row must survive any queue problem
        logger.exception("catalog competition enqueue failed for %s; the change is kept", entry.item_id)
        return False


def _consulted_within_gap(db: Session, mla: str, now: datetime) -> bool:
    gap = settings.ML_PUB_CATALOG_COMPETITION_CHANGE_GAP_SECONDS
    if gap <= 0:
        return False
    latest = db.query(func.max(MLCatalogCompetition.fecha_consulta)).filter(MLCatalogCompetition.mla == mla).scalar()
    return latest is not None and latest > now - timedelta(seconds=gap)
