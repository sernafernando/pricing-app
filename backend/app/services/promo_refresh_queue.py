"""Queue helpers of the promotions-mirror refresh that follows a publication reactivation.

Rows live in `promo_refresh_pending` (one per MLA, shared with the panel write path, see
`ml_promotions_write_service`). The store enqueues an MLA when its status goes back to `active`
(`events_store.write_events`); the `ml_publications.promo_refresh` worker handler drains the table.

Every function takes the caller's session and never commits: the enqueue joins the transaction that
wrote the event, and the handler wraps each step in its own short `get_background_db()` block.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, List, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.ml_publications import MlItem
from app.models.promo_refresh_pending import PromoRefreshPending

# A row that failed this many times is quarantined (deleted, logged by the caller).
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 60
BACKOFF_CAP_SECONDS = 3600
# A claimed row is invisible to other claims for this long; a worker that dies mid-call releases it by expiry.
CLAIM_LEASE_SECONDS = 300

OUTCOME_RESCHEDULED = "rescheduled"
OUTCOME_QUARANTINED = "quarantined"


def backoff_seconds(attempts: int) -> int:
    """Delay before the next try after `attempts` failures: 60 s, 120 s, 240 s, ... capped at one hour."""
    return min(BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), BACKOFF_CAP_SECONDS)


def enqueue(db, item_ids: Iterable[str], now: datetime) -> int:
    """Queue `item_ids` for a refresh due `now`; an MLA already queued is left as it is. Returns new rows."""
    values = [{"mla": item_id, "due_at": now, "attempts": 0} for item_id in dict.fromkeys(item_ids)]
    if not values:
        return 0
    statement = (
        pg_insert(PromoRefreshPending)
        .values(values)
        .on_conflict_do_nothing(index_elements=["mla"])
        .returning(PromoRefreshPending.id)
    )
    return len(db.execute(statement).all())


def claim_one(db, now: datetime) -> Optional[str]:
    """Oldest due MLA, leased until `now + CLAIM_LEASE_SECONDS`; None when nothing is due."""
    row = (
        db.query(PromoRefreshPending)
        .filter(PromoRefreshPending.due_at <= now)
        .order_by(PromoRefreshPending.due_at, PromoRefreshPending.id)
        .with_for_update(skip_locked=True)
        .first()
    )
    if row is None:
        return None
    row.due_at = now + timedelta(seconds=CLAIM_LEASE_SECONDS)
    db.flush()  # the lease is written before any bulk statement of the caller touches the row
    return row.mla


def is_active(db, mla: str) -> bool:
    """True only for a live, active publication in the store (the owner's rule: promotions are queried only then)."""
    row = db.query(MlItem.status, MlItem.gone_at, MlItem.never_existed).filter(MlItem.item_id == mla).first()
    return row is not None and row.status == "active" and row.gone_at is None and not row.never_existed


def drop(db, mla: str) -> None:
    db.query(PromoRefreshPending).filter(PromoRefreshPending.mla == mla).delete(synchronize_session=False)


def release(db, mla: str, now: datetime) -> None:
    """Make a claimed row due again without charging an attempt."""
    db.query(PromoRefreshPending).filter(PromoRefreshPending.mla == mla).update(
        {"due_at": now}, synchronize_session=False
    )


def fail(db, mla: str, now: datetime) -> Optional[str]:
    """Charge one failed attempt: back off, or quarantine (delete) at `MAX_ATTEMPTS`. None if the row is gone."""
    row = db.query(PromoRefreshPending).filter(PromoRefreshPending.mla == mla).first()
    if row is None:
        return None
    row.attempts += 1
    if row.attempts >= MAX_ATTEMPTS:
        db.delete(row)
        return OUTCOME_QUARANTINED
    row.due_at = now + timedelta(seconds=backoff_seconds(row.attempts))
    return OUTCOME_RESCHEDULED


def pending_mlas(db) -> List[str]:
    return [row.mla for row in db.query(PromoRefreshPending.mla).order_by(PromoRefreshPending.id)]
