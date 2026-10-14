"""Queue helpers of the promotions-mirror refresh that follows a publication reactivation.

Rows live in `promo_refresh_reactivation` (one per MLA; the panel's own `promo_refresh_pending` queue is left
to its own drainer, see `app/models/promo_refresh_reactivation.py`). The store enqueues an MLA when its status
goes back to `active` (`events_store.write_events`); the `ml_publications.promo_refresh` worker handler drains the table.

Every function takes the caller's session and never commits: the enqueue joins the transaction that
wrote the event, and the handler wraps each step in its own short `get_background_db()` block.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.ml_publications import MlItem
from app.models.promo_refresh_reactivation import PromoRefreshReactivation

logger = logging.getLogger(__name__)

# Every claim charges one attempt (so a MLA that crashes the worker mid-call cannot loop forever); a row whose
# attempts reach this number is quarantined (deleted, logged).
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
    """Queue `item_ids` for a refresh due `now`. An MLA already queued is made due again with a fresh budget, which
    also invalidates a lease in flight (see `Claim`), so a reactivation during a refresh is never swallowed by it."""
    values = [{"mla": item_id, "due_at": now, "attempts": 0} for item_id in dict.fromkeys(item_ids)]
    if not values:
        return 0
    insert = pg_insert(PromoRefreshReactivation).values(values)
    statement = insert.on_conflict_do_update(
        index_elements=["mla"], set_={"due_at": insert.excluded.due_at, "attempts": 0}
    ).returning(PromoRefreshReactivation.id)
    return len(db.execute(statement).all())


@dataclass(frozen=True)
class Claim:
    """A leased row. Settling it only touches the row while `due_at` still equals the lease: a newer `enqueue`
    changed it, and that newer request must survive this refresh."""

    mla: str
    leased_until: datetime


def claim_one(db, now: datetime) -> Optional[Claim]:
    """Oldest due MLA, leased until `now + CLAIM_LEASE_SECONDS` with one attempt charged; None when nothing is due.
    Rows that already used up their attempts (crashes mid-call never reach a settle) are quarantined on the way."""
    while True:
        row = (
            db.query(PromoRefreshReactivation)
            .filter(PromoRefreshReactivation.due_at <= now)
            .order_by(PromoRefreshReactivation.due_at, PromoRefreshReactivation.id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None:
            return None
        if row.attempts >= MAX_ATTEMPTS:
            logger.error("promo_refresh: %s QUARANTINED after %s attempts", row.mla, row.attempts)
            db.delete(row)
            db.flush()
            continue
        row.attempts += 1
        row.due_at = now + timedelta(seconds=CLAIM_LEASE_SECONDS)
        db.flush()
        return Claim(row.mla, row.due_at)


def is_active(db, mla: str) -> bool:
    """True only for a live, active publication in the store (the owner's rule: promotions are queried only then)."""
    row = db.query(MlItem.status, MlItem.gone_at, MlItem.never_existed).filter(MlItem.item_id == mla).first()
    return row is not None and row.status == "active" and row.gone_at is None and not row.never_existed


def _leased(db, claim: Claim):
    return db.query(PromoRefreshReactivation).filter(
        PromoRefreshReactivation.mla == claim.mla, PromoRefreshReactivation.due_at == claim.leased_until
    )


def drop(db, claim: Claim) -> None:
    """Remove the claimed row (done, or nothing a retry could fix), unless a newer enqueue replaced the lease."""
    _leased(db, claim).delete(synchronize_session=False)


def release(db, claim: Claim, now: datetime) -> None:
    """Hand the claim back, due again and uncharged."""
    _leased(db, claim).update(
        {"due_at": now, "attempts": PromoRefreshReactivation.attempts - 1}, synchronize_session=False
    )


def fail(db, claim: Claim, now: datetime) -> Optional[str]:
    """The attempt claimed failed: back off, or quarantine (delete) at `MAX_ATTEMPTS`. None if the lease was replaced."""
    row = _leased(db, claim).first()
    if row is None:
        return None
    if row.attempts >= MAX_ATTEMPTS:
        db.delete(row)
        return OUTCOME_QUARANTINED
    row.due_at = now + timedelta(seconds=backoff_seconds(row.attempts))
    return OUTCOME_RESCHEDULED
