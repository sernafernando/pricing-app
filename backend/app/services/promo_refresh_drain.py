"""Drain of `promo_refresh_pending`: the ~60 s follow-up refresh a promo write queues.

After an enroll/remove, `ml_promotions_write_service._enqueue_refresh_retry` upserts one row per MLA due
`REFRESH_RETRY_DELAY_SECONDS` later, because the immediate refresh often still reads `candidate` before ML
settles. This module refreshes the ml-webhook promo mirror for the due rows. It is run by the
`promo_write.refresh` worker handler (no cron); `app/scripts/drain_promo_refresh.py` runs one pass by hand.

One pass (`drain`):
  1. Kill switch first: with `PROMOS_WRITE_ENABLED` off it reads and writes nothing.
  2. Stale backlog: rows whose `due_at` is older than `STALE_AFTER` are deleted, at most `STALE_PURGE_BATCH`
     per pass, without a refresh. The mirror is refreshed by other paths anyway (webhooks, backfill), and
     replaying a backlog of thousands would hammer ML. `due_at`, not `created_at`, decides: the write
     upsert resets `due_at` but keeps `created_at`, so an MLA written again today must not count as stale.
  3. Due rows, oldest-due first, at most `MAX_ROWS_PER_RUN` per pass and none started after `deadline`.
     Each row is claimed alone in a short session (`FOR UPDATE SKIP LOCKED`, one attempt charged, `due_at`
     pushed to a lease), refreshed with NO session open, then settled in another short session: deleted on
     success, dropped when retrying cannot help, otherwise retried `REFRESH_RETRY_DELAY_SECONDS` later and
     quarantined (deleted, logged) at `MAX_ATTEMPTS`. A settle only touches the row while `due_at` still
     equals the lease, so a new write that re-queued the MLA during the call survives it.
  4. After a successful refresh, outside any session: `promo_write_confirmation.confirm_recent_writes` records
     whether ML actually applied the MLA's recent writes. Best effort; it never changes the settle or the counts.

The lease replaces the old session-level advisory lock, which had to keep a connection open for the whole pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from app.core.config import settings
from app.core.database import get_background_db
from app.models.promo_refresh_pending import PromoRefreshPending
from app.services.ml_promotions_write_service import REFRESH_RETRY_DELAY_SECONDS
from app.services.ml_webhook_client import RefreshOutcome, ml_webhook_client
from app.services.promo_write_confirmation import confirm_recent_writes
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

# Failed attempts before a row is quarantined (deleted, logged) instead of retried.
MAX_ATTEMPTS = 5
# Rows refreshed per pass at most; the rest are taken by the next pass.
MAX_ROWS_PER_RUN = 50
# A row due longer ago than this is no longer worth a refresh: dropped, not replayed.
STALE_AFTER = timedelta(hours=24)
# Stale rows deleted per pass at most, so a large backlog is cleared in short statements.
STALE_PURGE_BATCH = 1000
# A claimed row is invisible to other passes for this long; a pass that dies mid-call frees it by expiry.
CLAIM_LEASE_SECONDS = 300


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# What a settle does with a claimed row, given the outcome of its refresh (`decide`).
REFRESHED = "refreshed"
DROPPED = "dropped"
RETRY = "retry"
QUARANTINE = "quarantine"


@dataclass(frozen=True)
class Claim:
    mla: str
    leased_until: datetime


def stale_cutoff(now: datetime) -> datetime:
    """Rows due before this instant are stale: dropped by the purge, never claimed."""
    return now - STALE_AFTER


def is_stale(due_at: datetime, now: datetime) -> bool:
    return due_at < stale_cutoff(now)


def decide(outcome: Optional[RefreshOutcome], attempts: int) -> str:
    """The settle rule. `outcome` None means the call raised (a retryable failure); `attempts` already includes
    the one charged by this claim."""
    if outcome is not None and outcome.ok:
        return REFRESHED
    if outcome is not None and not outcome.reintentable:
        # The item's own condition (closed, not eligible): retrying spends calls on something that cannot change.
        return DROPPED
    return QUARANTINE if attempts >= MAX_ATTEMPTS else RETRY


def retry_due_at(now: datetime) -> datetime:
    return now + timedelta(seconds=REFRESH_RETRY_DELAY_SECONDS)


def purge_stale(db, now: datetime) -> int:
    """Delete up to `STALE_PURGE_BATCH` stale rows. Returns how many."""
    ids = [
        row.id
        for row in db.query(PromoRefreshPending.id)
        .filter(PromoRefreshPending.due_at < stale_cutoff(now))
        .order_by(PromoRefreshPending.due_at, PromoRefreshPending.id)
        .limit(STALE_PURGE_BATCH)
        .with_for_update(skip_locked=True)
        .all()
    ]
    if not ids:
        return 0
    db.query(PromoRefreshPending).filter(PromoRefreshPending.id.in_(ids)).delete(synchronize_session=False)
    return len(ids)


def claim_one(db, now: datetime) -> tuple[Optional[Claim], int]:
    """Lease the oldest due, non-stale row, charging one attempt. Returns the claim (None when nothing is due) and
    how many rows were quarantined on the way (already out of attempts: a pass died mid-call on them)."""
    quarantined = 0
    while True:
        row = (
            db.query(PromoRefreshPending)
            # Stale rows the purge has not reached yet are left for it, never replayed.
            .filter(PromoRefreshPending.due_at <= now, PromoRefreshPending.due_at >= stale_cutoff(now))
            .order_by(PromoRefreshPending.due_at, PromoRefreshPending.id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None:
            return None, quarantined
        if row.attempts >= MAX_ATTEMPTS:
            logger.error("promo_write.refresh: %s QUARANTINED after %s attempts", row.mla, row.attempts)
            db.delete(row)
            db.flush()
            quarantined += 1
            continue
        row.attempts += 1
        row.due_at = now + timedelta(seconds=CLAIM_LEASE_SECONDS)
        db.flush()
        return Claim(row.mla, row.due_at), quarantined


def _refresh(mla: str) -> Optional[RefreshOutcome]:
    """The proxy call, outside any session. Never raises: an exception is a retryable failure (None)."""
    try:
        return resolve_maybe_async(ml_webhook_client.refresh_item_promotions(mla))
    except Exception:  # noqa: BLE001 -- one MLA must not stop the others
        logger.warning("promo_write.refresh: refresh_item_promotions raised for %s", mla, exc_info=True)
        return None


def _settle(db, claim: Claim, outcome: Optional[RefreshOutcome], detail: Dict[str, Any]) -> None:
    # Locked, so a write re-queueing the MLA right now waits for this settle instead of being swallowed by it.
    row = (
        db.query(PromoRefreshPending)
        .filter(PromoRefreshPending.mla == claim.mla, PromoRefreshPending.due_at == claim.leased_until)
        .with_for_update()
        .first()
    )
    if row is None:  # a new write re-queued the MLA during the call; its fresh row stands, nothing is counted
        detail["superseded"] += 1
        return
    decision = decide(outcome, row.attempts)
    if decision == DROPPED:
        logger.warning("promo_write.refresh: %s dropped, not retryable: %s", claim.mla, outcome.motivo)
    if decision in (REFRESHED, DROPPED):
        db.delete(row)
        detail[decision] += 1
        return
    detail["failed"] += 1
    if decision == QUARANTINE:
        logger.error("promo_write.refresh: %s QUARANTINED after %s attempts", claim.mla, row.attempts)
        db.delete(row)
        detail["quarantined"] += 1
        return
    if outcome is not None:
        logger.warning("promo_write.refresh: %s failed, retrying later: %s", claim.mla, outcome.motivo)
    row.due_at = retry_due_at(_utcnow())


def drain(
    *,
    deadline: Optional[datetime],
    session_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    """One pass (see the module docstring). Returns counts for the handler result.

    Each DB step runs in its own `get_background_db()` block, which commits on exit and rolls back on error. A DB
    error is logged, counted in `errors` and does not stop the pass: a row whose settle failed keeps its lease
    and is claimed again when the lease expires. A claim error still takes a slot of `MAX_ROWS_PER_RUN`, so a
    database that keeps failing cannot spin the pass."""
    if not settings.PROMOS_WRITE_ENABLED:
        return {"skipped": "PROMOS_WRITE_ENABLED is off"}
    sessions = session_factory or get_background_db
    detail: Dict[str, Any] = {
        "stale_dropped": 0,
        "refreshed": 0,
        "dropped": 0,
        "failed": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
        "capped": False,
    }
    # `get_background_db()` commits on a clean exit (app/core/database.py), so each block below is its own txn.
    try:
        with sessions() as db:
            detail["stale_dropped"] = purge_stale(db, _utcnow())
    except Exception:  # noqa: BLE001 -- the due rows still deserve their refresh
        logger.error("promo_write.refresh: purging stale rows failed", exc_info=True)
        detail["errors"] += 1
    if detail["stale_dropped"]:
        logger.info("promo_write.refresh: dropped %s stale rows without a refresh", detail["stale_dropped"])

    taken = 0
    while True:
        if deadline is not None and _utcnow() >= deadline:
            detail["stopped"] = "deadline"
            break
        if taken >= MAX_ROWS_PER_RUN:
            detail["capped"] = True
            break
        taken += 1
        try:
            with sessions() as db:
                claim, quarantined = claim_one(db, _utcnow())
        except Exception:  # noqa: BLE001 -- nothing was leased; the next claim tries again
            logger.error("promo_write.refresh: claiming a row failed", exc_info=True)
            detail["errors"] += 1
            continue
        detail["quarantined"] += quarantined
        if claim is None:
            break
        outcome = _refresh(claim.mla)
        try:
            with sessions() as db:
                _settle(db, claim, outcome, detail)
        except Exception:  # noqa: BLE001 -- the row keeps its lease and is claimed again once it expires
            logger.error("promo_write.refresh: settling %s failed", claim.mla, exc_info=True)
            detail["errors"] += 1
        if outcome is not None and outcome.ok:
            _confirm(claim.mla, sessions)
    return detail


def _confirm(mla: str, sessions: Callable[[], Any]) -> None:
    """The mirror is fresh: record whether ML applied the recent writes (P3). After the settle and outside its
    session; best effort, so it never changes the settle or the counts."""
    try:
        confirm_recent_writes(mla, session_factory=sessions)
    except Exception:  # noqa: BLE001 -- confirm_recent_writes never raises; this guards a bug in it
        logger.warning("promo_write.refresh: confirming writes for %s failed", mla, exc_info=True)
