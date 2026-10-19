"""Did ML actually apply our promo writes? (promo-write-refresh P3)

ML can accept an enroll (2xx, outcome `submitted`) and still leave the item `candidate`: on 2026-10-19 it accepted
six enrolls of MLA1610390994 in C-MLA1669550 and the promo never started. Nobody told the PM.

Two halves:
  - `confirm_recent_writes(mla)`: called by the `promo_refresh_pending` drain right after a successful refresh,
    when the mirror is fresh. It stamps `payload.confirmation = {status, mirror_status, checked_at}` on the latest
    recent `ml_write_log` row per promotion. Best effort: it never raises.
  - `advertencias_de_escritura(db, mla, promotions)`: the panel read. One batched query for the latest write per
    promotion, turned into a per-row warning or a panel-level one for a promotion the mirror no longer shows.

The rule itself is `write_took_effect` in `ml_promotions_write_service`, shared with the ambiguous-write
reconciliation. No migration: the confirmation lives in the existing `payload` JSONB.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from sqlalchemy import text

from app.core.database import get_background_db
from app.models.ml_write_log import ACTION_ENROLL, RESOURCE_PROMOTION
from app.services.ml_promotions_service import fetch_item_promotions
from app.services.ml_promotions_write_service import write_took_effect

logger = logging.getLogger(__name__)

# Writes older than this are not confirmed: the drain refreshes ~60 s after a write (retrying for a few minutes),
# so a row this old was settled by another path and a confirmation now would describe a different moment.
CONFIRM_WINDOW = timedelta(minutes=15)
# The panel only warns about writes this recent; it also bounds the panel query on (mla, created_at).
WARNING_LOOKBACK = timedelta(days=30)

APPLIED = "applied"
NOT_APPLIED = "not_applied"

# Latest row per promotion of one MLA (`DISTINCT ON`, Postgres). Only rows written for a confirmed write exist:
# `_record_write_log` skips rejected and AMBIGUOUS outcomes, so an ambiguous write has no row and is out of scope
# here (its own reconciliation already reported it as such).
_LATEST_UNCONFIRMED_SQL = text(
    """
    SELECT DISTINCT ON (target_id) id, action, target_id, (payload -> 'confirmation') IS NOT NULL AS confirmed
    FROM ml_write_log
    WHERE mla = :mla AND resource = :resource AND target_id IS NOT NULL AND created_at >= :since
    ORDER BY target_id, created_at DESC, id DESC
    """
)

# Merges the key into the existing payload. The `IS NULL` guard keeps a confirmation written by an overlapping
# drain pass: the first one wins, nothing is overwritten.
_SET_CONFIRMATION_SQL = text(
    """
    UPDATE ml_write_log
    SET payload = jsonb_set(COALESCE(payload, '{}'::jsonb), '{confirmation}', CAST(:confirmation AS jsonb))
    WHERE id = :id AND (payload -> 'confirmation') IS NULL
    """
)

_LATEST_FOR_PANEL_SQL = text(
    """
    SELECT DISTINCT ON (w.target_id)
        w.target_id AS promotion_id, w.action, w.created_at, w.usuario_id, u.nombre,
        w.payload -> 'confirmation' AS confirmation
    FROM ml_write_log w
    LEFT JOIN usuarios u ON u.id = w.usuario_id
    WHERE w.mla = :mla AND w.resource = :resource AND w.target_id IS NOT NULL AND w.created_at >= :since
    ORDER BY w.target_id, w.created_at DESC, w.id DESC
    """
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def confirmation_for(action: str, mirror_status: Optional[str], checked_at: datetime) -> Dict[str, Any]:
    """The `payload.confirmation` value for one write, given its promotion's status in a fresh mirror
    (None when the mirror has no row for it)."""
    return {
        "status": APPLIED if write_took_effect(action, mirror_status) else NOT_APPLIED,
        "mirror_status": mirror_status,
        "checked_at": checked_at.isoformat(),
    }


def confirm_recent_writes(mla: str, *, session_factory: Optional[Callable[[], Any]] = None) -> int:
    """Stamp a confirmation on the latest unconfirmed write per promotion of `mla` from the last `CONFIRM_WINDOW`.

    Returns how many rows were stamped. Never raises: a failure is logged and returns 0, and the drain that
    calls it settles and counts exactly as without it. Two short sessions, none open during the mirror read."""
    sessions = session_factory or get_background_db
    try:
        now = _utcnow()
        with sessions() as db:
            rows = db.execute(
                _LATEST_UNCONFIRMED_SQL,
                {"mla": mla, "resource": RESOURCE_PROMOTION, "since": now - CONFIRM_WINDOW},
            ).all()
        pending = [row for row in rows if not row.confirmed]
        if not pending:
            return 0
        statuses = {promo.get("promotion_id"): promo.get("status") for promo in fetch_item_promotions(mla)}
        checked_at = _utcnow()
        stamped = 0
        with sessions() as db:
            for row in pending:
                value = confirmation_for(row.action, statuses.get(row.target_id), checked_at)
                stamped += db.execute(_SET_CONFIRMATION_SQL, {"id": row.id, "confirmation": json.dumps(value)}).rowcount
                if value["status"] == NOT_APPLIED:
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


def latest_writes_by_promotion(db, mla: str) -> List[Dict[str, Any]]:
    """The latest write per promotion of `mla` within `WARNING_LOOKBACK`, in one query, with the user's name."""
    rows = db.execute(
        _LATEST_FOR_PANEL_SQL,
        {"mla": mla, "resource": RESOURCE_PROMOTION, "since": _utcnow() - WARNING_LOOKBACK},
    ).mappings()
    return [dict(row) for row in rows]


def _usuario(write: Mapping[str, Any]) -> Optional[str]:
    """Display name; the id when the user row is gone; None for a system write."""
    if write.get("nombre"):
        return write["nombre"]
    if write.get("usuario_id") is not None:
        return f"#{write['usuario_id']}"
    return None


def warnings_from_latest_writes(
    latest: Iterable[Mapping[str, Any]], shown_statuses: Mapping[str, Optional[str]]
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Split the not-applied latest writes into per-row warnings and panel-level ones.

    `shown_statuses` maps each promotion the panel shows to its current mirror status. A write confirmed
    `not_applied` warns only while the current status still says so: ML may apply it later, and the current mirror
    wins. An enroll whose promotion the panel does not show warns at panel level; a remove of a promotion no longer
    shown took effect (a missing row counts as removed)."""
    por_promo: Dict[str, Dict[str, Any]] = {}
    sin_promo: List[Dict[str, Any]] = []
    for write in latest:
        conf = write.get("confirmation") or {}
        if conf.get("status") != NOT_APPLIED:
            continue
        promotion_id = write["promotion_id"]
        aviso = {"accion": write["action"], "fecha": write["created_at"], "usuario": _usuario(write)}
        if promotion_id in shown_statuses:
            if not write_took_effect(write["action"], shown_statuses[promotion_id]):
                por_promo[promotion_id] = aviso
        elif write["action"] == ACTION_ENROLL:
            sin_promo.append({"promotion_id": promotion_id, **aviso, "estado_ml": conf.get("mirror_status")})
    return por_promo, sin_promo


def advertencias_de_escritura(
    db, mla: str, promotions: Iterable[Mapping[str, Any]]
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Per-row and panel-level warnings for the promotions the panel shows. Raises on a DB error; the
    router decides what a failure means for the panel."""
    shown = {promo.get("promotion_id"): promo.get("status") for promo in promotions}
    return warnings_from_latest_writes(latest_writes_by_promotion(db, mla), shown)
