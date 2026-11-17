"""Lean audit writers for hay_mejores (flag transition + Auto toggle)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ml_hay_mejores_audit import (
    KIND_AUTO_TOGGLE,
    KIND_FLAG_TRANSITION,
    MlHayMejoresAudit,
)

logger = get_logger(__name__)


def record_flag_transition(
    db: Session,
    item_id: str,
    *,
    payload: Mapping[str, Any],
    usuario_id: Optional[int] = None,
) -> None:
    """Append a flag_transition row. Caller must only invoke on real transitions.

    Never raises — audit loss must not poison the flag savepoint.
    """
    try:
        db.add(
            MlHayMejoresAudit(
                item_id=item_id,
                kind=KIND_FLAG_TRANSITION,
                usuario_id=usuario_id,
                payload=dict(payload),
            )
        )
        db.flush()
    except Exception as exc:
        logger.warning("hay_mejores audit flag_transition failed for %s: %s", item_id, exc)


def record_auto_toggle(
    db: Session,
    item_id: str,
    *,
    old: bool,
    new: bool,
    usuario_id: Optional[int],
    alcance: str = "item",
) -> None:
    """Append an auto_toggle row when Auto-aplicación flips. Never raises."""
    if old == new:
        return
    try:
        db.add(
            MlHayMejoresAudit(
                item_id=item_id,
                kind=KIND_AUTO_TOGGLE,
                usuario_id=usuario_id,
                payload={"old": old, "new": new, "alcance": alcance},
            )
        )
        db.flush()
    except Exception as exc:
        logger.warning("hay_mejores audit auto_toggle failed for %s: %s", item_id, exc)


def latest_flag_transition_payload(db: Session, item_id: str) -> Optional[dict[str, Any]]:
    """Most recent flag_transition payload for enroll enrich, or None."""
    row = (
        db.query(MlHayMejoresAudit)
        .filter(
            MlHayMejoresAudit.item_id == item_id,
            MlHayMejoresAudit.kind == KIND_FLAG_TRANSITION,
        )
        .order_by(MlHayMejoresAudit.created_at.desc(), MlHayMejoresAudit.id.desc())
        .first()
    )
    if row is None or not isinstance(row.payload, dict):
        return None
    return dict(row.payload)
