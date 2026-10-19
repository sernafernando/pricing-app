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


@dataclass(frozen=True)
class Claim:
    mla: str
    leased_until: datetime


def purge_stale(db, now: datetime) -> int:
    """Delete up to `STALE_PURGE_BATCH` rows due before `now - STALE_AFTER`. Returns how many."""
    ids = [
        row.id
        for row in db.query(PromoRefreshPending.id)
        .filter(PromoRefreshPending.due_at < now - STALE_AFTER)
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
    """Lease the oldest due, non-stale row, charging one attempt. Returns the claim (None when nothing is due) and how many
    rows were quarantined on the way (already out of attempts: a pass died mid-call on them)."""
    quarantined = 0
    while True:
        row = (
            db.query(PromoRefreshPending)
            # Stale rows the purge has not reached yet are left for it, never replayed.
            .filter(PromoRefreshPending.due_at <= now, PromoRefreshPending.due_at >= now - STALE_AFTER)
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


def _leased(db, claim: Claim):
    return db.query(PromoRefreshPending).filter(
        PromoRefreshPending.mla == claim.mla, PromoRefreshPending.due_at == claim.leased_until
    )


def _refresh(mla: str) -> Optional[RefreshOutcome]:
    """The proxy call, outside any session. Never raises: an exception is a retryable failure (None)."""
    try:
        return resolve_maybe_async(ml_webhook_client.refresh_item_promotions(mla))
    except Exception:  # noqa: BLE001 -- one MLA must not stop the others
        logger.warning("promo_write.refresh: refresh_item_promotions raised for %s", mla, exc_info=True)
        return None


def _settle(db, claim: Claim, outcome: Optional[RefreshOutcome], detail: Dict[str, Any]) -> None:
    if outcome is not None and outcome.ok:
        _leased(db, claim).delete(synchronize_session=False)
        detail["refreshed"] += 1
        return
    if outcome is not None and not outcome.reintentable:
        # The item's own condition (closed, not eligible): retrying spends calls on something that cannot change.
        logger.warning("promo_write.refresh: %s dropped, not retryable: %s", claim.mla, outcome.motivo)
        _leased(db, claim).delete(synchronize_session=False)
        detail["dropped"] += 1
        return
    row = _leased(db, claim).first()
    if row is None:  # a new write re-queued the MLA during the call; its fresh row stands
        return
    detail["failed"] += 1
    if row.attempts >= MAX_ATTEMPTS:
        logger.error("promo_write.refresh: %s QUARANTINED after %s attempts", claim.mla, row.attempts)
        db.delete(row)
        detail["quarantined"] += 1
        return
    if outcome is not None:
        logger.warning("promo_write.refresh: %s failed, retrying later: %s", claim.mla, outcome.motivo)
    row.due_at = _utcnow() + timedelta(seconds=REFRESH_RETRY_DELAY_SECONDS)


def drain(
    *,
    deadline: Optional[datetime],
    session_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    """One pass (see the module docstring). Returns counts for the handler result."""
    if not settings.PROMOS_WRITE_ENABLED:
        return {"skipped": "PROMOS_WRITE_ENABLED is off"}
    sessions = session_factory or get_background_db
    detail: Dict[str, Any] = {
        "stale_dropped": 0,
        "refreshed": 0,
        "dropped": 0,
        "failed": 0,
        "quarantined": 0,
        "capped": False,
    }
    with sessions() as db:
        detail["stale_dropped"] = purge_stale(db, _utcnow())
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
        with sessions() as db:
            claim, quarantined = claim_one(db, _utcnow())
        detail["quarantined"] += quarantined
        if claim is None:
            break
        taken += 1
        outcome = _refresh(claim.mla)
        with sessions() as db:
            _settle(db, claim, outcome, detail)
    return detail
