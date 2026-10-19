"""Did ML actually apply our promo writes? (promo-write-refresh P3)

ML can accept an enroll (2xx, outcome `submitted`) and still leave the item `candidate`: on 2026-10-19 it accepted
six enrolls of MLA1610390994 in C-MLA1669550 and the promo never started. Nobody told the PM.

`confirm_recent_writes(mla)` is called by the `promo_refresh_pending` drain right after a successful refresh, when
the mirror is fresh. It stamps `payload.confirmation = {status, mirror_status, checked_at}` on the latest recent
`ml_write_log` row per promotion. Only `applied` is final: a `not_applied` stamp is re-checked by later passes while
the write is inside `CONFIRM_WINDOW`, because `created_at` is the transaction start and a write can fall under the
read bound while still missing from the snapshot. Best effort: it never raises.

The rule itself is `write_took_effect` in `ml_promotions_write_service`, shared with the ambiguous-write
reconciliation. No migration: the confirmation lives in the existing `payload` JSONB.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text

from app.core.database import get_background_db
from app.models.ml_write_log import RESOURCE_PROMOTION
from app.services.ml_promotions_service import fetch_item_promotions
from app.services.ml_promotions_write_service import write_took_effect

logger = logging.getLogger(__name__)

# Writes older than this are not confirmed: the drain refreshes ~60 s after a write (retrying for a few minutes),
# so a row this old was settled by another path and a confirmation now would describe a different moment.
CONFIRM_WINDOW = timedelta(minutes=15)

APPLIED = "applied"
NOT_APPLIED = "not_applied"

# Latest row per promotion of one MLA (`DISTINCT ON`, Postgres) among the writes made in [since, until]. Only rows
# written for a confirmed write exist: `_record_write_log` skips rejected and AMBIGUOUS outcomes, so an ambiguous
# write has no row and is out of scope here (its own reconciliation already reported it as such).
_LATEST_UNCONFIRMED_SQL = text(
    """
    SELECT DISTINCT ON (target_id) id, action, target_id, payload -> 'confirmation' ->> 'status' AS status
    FROM ml_write_log
    WHERE mla = :mla AND resource = :resource AND target_id IS NOT NULL
      AND created_at >= :since AND created_at <= :until
    ORDER BY target_id, created_at DESC, id DESC
    """
)

# Merges the key into the existing payload and returns the status it replaced (NULL when unstamped). Only
# `applied` is final: the guard lets a pass overwrite an unstamped or `not_applied` row and never an `applied` one,
# so two overlapping passes never downgrade it. The CTE locks the row and reads its current stamp after any
# concurrent update, which makes the returned status the one actually replaced.
_SET_CONFIRMATION_SQL = text(
    """
    WITH prev AS (
        SELECT id, payload -> 'confirmation' ->> 'status' AS status FROM ml_write_log WHERE id = :id FOR UPDATE
    )
    UPDATE ml_write_log w
    SET payload = jsonb_set(COALESCE(w.payload, '{}'::jsonb), '{confirmation}', CAST(:confirmation AS jsonb))
    FROM prev
    WHERE w.id = prev.id AND prev.status IS DISTINCT FROM 'applied'
    RETURNING prev.status
    """
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _db_now(sessions: Callable[[], Any]) -> datetime:
    """The database's current time. `ml_write_log.created_at` is stamped by Postgres, so a bound compared against
    it must come from the same clock: an app clock running ahead would let a later write fall under the bound."""
    with sessions() as db:
        return db.execute(text("SELECT clock_timestamp()")).scalar_one()


def confirmation_for(action: str, mirror_status: Optional[str], checked_at: datetime) -> Dict[str, Any]:
    """The `payload.confirmation` value for one write, given its promotion's status in a fresh mirror
    (None when the mirror has no row for it)."""
    return {
        "status": APPLIED if write_took_effect(action, mirror_status) else NOT_APPLIED,
        "mirror_status": mirror_status,
        "checked_at": checked_at.isoformat(),
    }


def _pending(sessions: Callable[[], Any], mla: str, since: datetime, until: datetime) -> List[Any]:
    """The latest write per promotion made in [since, until], kept unless it is already confirmed `applied`."""
    with sessions() as db:
        rows = db.execute(
            _LATEST_UNCONFIRMED_SQL,
            {"mla": mla, "resource": RESOURCE_PROMOTION, "since": since, "until": until},
        ).all()
    return [row for row in rows if row.status != APPLIED]


def confirm_recent_writes(mla: str, *, session_factory: Optional[Callable[[], Any]] = None) -> int:
    """Stamp a confirmation on the latest write per promotion of `mla` from the last `CONFIRM_WINDOW`, unless it
    is already `applied`.

    Only writes made up to the mirror read are stamped: a later one is not reflected in that snapshot. It stays
    unstamped and a later pass confirms it (the write re-queued the MLA for the drain). A `not_applied` stamp is
    provisional and is re-checked here; `applied` is final. The "not applied by ML" warning is logged once, when an
    unstamped write is first stamped `not_applied`.

    Returns how many rows changed status (unstamped to a status, or `not_applied` to `applied`). Never raises: a
    failure is logged and returns 0, and the drain that calls it settles and counts exactly as without it. Short
    sessions, none open during the mirror read."""
    sessions = session_factory or get_background_db
    try:
        now = _utcnow()
        since = now - CONFIRM_WINDOW
        if not _pending(sessions, mla, since, now):
            return 0
        read_at = _db_now(sessions)  # just before the read, on the DB clock: a write after it may be missing
        statuses = {promo.get("promotion_id"): promo.get("status") for promo in fetch_item_promotions(mla)}
        checked_at = _utcnow()
        stamped = 0
        # Re-read the latest write per promotion as of `read_at`: the one the snapshot can actually speak for.
        pending = _pending(sessions, mla, since, read_at)
        with sessions() as db:
            for row in pending:
                value = confirmation_for(row.action, statuses.get(row.target_id), checked_at)
                replaced = db.execute(_SET_CONFIRMATION_SQL, {"id": row.id, "confirmation": json.dumps(value)}).first()
                if replaced is None:  # already `applied`, by an overlapping pass: final, left alone
                    continue
                if replaced.status != value["status"]:
                    stamped += 1
                if replaced.status is None and value["status"] == NOT_APPLIED:
                    logger.warning(
                        "promo write not applied by ML: mla=%s action=%s promotion_id=%s mirror_status=%s",
                        mla,
                        row.action,
                        row.target_id,
                        value["mirror_status"],
                    )
        return stamped
    except Exception:  # noqa: BLE001 -- best effort: the write already happened, the drain must go on
        logger.warning("promo_write.refresh: confirming recent writes failed for %s", mla, exc_info=True)
        return 0
