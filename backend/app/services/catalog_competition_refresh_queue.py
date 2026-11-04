"""Enqueue / claim / settle for `catalog_competition_refresh_pending`.

Same lease shape as `promo_refresh_queue`: one row per MLA, claim bumps
`attempts` and pushes `due_at` forward as a lease; settle only touches the
row while `due_at` still equals that lease so a newer enqueue survives.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.catalog_competition_refresh_pending import CatalogCompetitionRefreshPending

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 60
BACKOFF_CAP_SECONDS = 3600
CLAIM_LEASE_SECONDS = 300

OUTCOME_RESCHEDULED = "rescheduled"
OUTCOME_QUARANTINED = "quarantined"


def backoff_seconds(attempts: int) -> int:
    return min(BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), BACKOFF_CAP_SECONDS)


def enqueue(db: Session, item_ids: Iterable[str], now: datetime) -> int:
    """Queue MLAs due `now`. An already-queued MLA is made due again with attempts reset."""
    values = [{"mla": item_id, "due_at": now, "attempts": 0} for item_id in dict.fromkeys(item_ids) if item_id]
    if not values:
        return 0
    insert = pg_insert(CatalogCompetitionRefreshPending).values(values)
    statement = insert.on_conflict_do_update(
        index_elements=["mla"],
        set_={"due_at": insert.excluded.due_at, "attempts": 0},
    ).returning(CatalogCompetitionRefreshPending.id)
    return len(db.execute(statement).all())


@dataclass(frozen=True)
class Claim:
    mla: str
    leased_until: datetime


def claim_one(db: Session, now: datetime) -> Optional[Claim]:
    while True:
        row = (
            db.query(CatalogCompetitionRefreshPending)
            .filter(CatalogCompetitionRefreshPending.due_at <= now)
            .order_by(CatalogCompetitionRefreshPending.due_at, CatalogCompetitionRefreshPending.id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None:
            return None
        if row.attempts >= MAX_ATTEMPTS:
            logger.error(
                "catalog_competition_refresh: %s QUARANTINED after %s attempts",
                row.mla,
                row.attempts,
            )
            db.delete(row)
            db.flush()
            continue
        row.attempts += 1
        row.due_at = now + timedelta(seconds=CLAIM_LEASE_SECONDS)
        db.flush()
        return Claim(row.mla, row.due_at)


def _leased(db: Session, claim: Claim):
    return db.query(CatalogCompetitionRefreshPending).filter(
        CatalogCompetitionRefreshPending.mla == claim.mla,
        CatalogCompetitionRefreshPending.due_at == claim.leased_until,
    )


def drop(db: Session, claim: Claim) -> None:
    row = _leased(db, claim).one_or_none()
    if row is not None:
        db.delete(row)
        db.flush()


def release(db: Session, claim: Claim, now: datetime) -> None:
    """Put a claimed row back due now (worker hit deadline before the ML call)."""
    row = _leased(db, claim).one_or_none()
    if row is None:
        return
    row.attempts = max(row.attempts - 1, 0)
    row.due_at = now
    db.flush()


def fail(db: Session, claim: Claim, now: datetime) -> str:
    """Backoff or quarantine after a failed refresh. Returns outcome token."""
    row = _leased(db, claim).one_or_none()
    if row is None:
        return OUTCOME_RESCHEDULED
    if row.attempts >= MAX_ATTEMPTS:
        logger.error(
            "catalog_competition_refresh: %s QUARANTINED after failed refresh (%s attempts)",
            row.mla,
            row.attempts,
        )
        db.delete(row)
        db.flush()
        return OUTCOME_QUARANTINED
    row.due_at = now + timedelta(seconds=backoff_seconds(row.attempts))
    db.flush()
    return OUTCOME_RESCHEDULED
