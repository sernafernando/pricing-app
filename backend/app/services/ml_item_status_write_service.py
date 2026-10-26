"""Pause or activate one publication at ML, through the ml-webhook proxy.

Order: kill switch -> the store's status (only an active publication is paused and only a paused one activated; a
deleted one, one ML never reported, or one in any other status is refused without calling ML) -> one write, never
retried -> on a confirmed write, an `ml_write_log` row with the user -> a manual-lane refresh of the item, also after an
ambiguous write or a no-op, so the store learns what ML has now.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_write_log import ACTION_ACTIVATE, ACTION_PAUSE, RESOURCE_ITEM, MlWriteLog
from app.services.ml_publication_status_service import (
    GONE,
    NEVER_EXISTED,
    NO_ML_DATA,
    fetch_publication_status_by_mla,
)
from app.services.ml_publications import queue as ml_pub_queue
from app.services.ml_publications.resources import CORE_RESOURCE
from app.services.ml_webhook_client import MLWebhookClient

logger = logging.getLogger(__name__)

SUBMITTED = "submitted"
DISABLED = "disabled"
NOT_ELIGIBLE = "not_eligible"
UNCHANGED = "unchanged"
REJECTED = "rejected"
AMBIGUOUS = "ambiguous"

PAUSED = "paused"
ACTIVE = "active"

# The status a publication must have for each target: ML refuses to activate a closed or under-review item, and
# pausing anything but an active one is meaningless.
_FROM = {PAUSED: ACTIVE, ACTIVE: PAUSED}
_ACTIONS = {PAUSED: ACTION_PAUSE, ACTIVE: ACTION_ACTIVATE}


@dataclass(frozen=True)
class ItemStatusOutcome:
    status: str
    message: Optional[str]


async def set_item_status(db: Session, mla: str, target: str, usuario_id: Optional[int]) -> ItemStatusOutcome:
    if not settings.ML_ITEM_STATUS_WRITE_ENABLED:
        return ItemStatusOutcome(DISABLED, "Pausar y activar publicaciones está deshabilitado.")

    current = fetch_publication_status_by_mla(db, [mla]).get(mla)
    if current is None or current.status == NO_ML_DATA:
        return ItemStatusOutcome(NOT_ELIGIBLE, "Todavía no hay datos de Mercado Libre para esta publicación.")
    if current.status in (GONE, NEVER_EXISTED) or "deleted" in (current.sub_status or ()):
        return ItemStatusOutcome(NOT_ELIGIBLE, "La publicación está eliminada.")
    if current.status == target:
        _enqueue_refresh_safely(mla)
        return ItemStatusOutcome(UNCHANGED, None)
    if current.status != _FROM[target]:
        return ItemStatusOutcome(NOT_ELIGIBLE, f"Una publicación en estado {current.status} no se puede cambiar.")

    result = await MLWebhookClient().put_item_status(mla, target)
    if result["ok"]:
        _record_write_log(mla, target, usuario_id)
        _enqueue_refresh_safely(mla)
        return ItemStatusOutcome(SUBMITTED, None)
    if result["ambiguous"]:
        _enqueue_refresh_safely(mla)
        return ItemStatusOutcome(AMBIGUOUS, "No se sabe si Mercado Libre aplicó el cambio: se vuelve a consultar.")
    body = result["body"]
    message = body.get("message") if isinstance(body, dict) else None
    return ItemStatusOutcome(REJECTED, message or "Mercado Libre rechazó el cambio.")


def _record_write_log(mla: str, target: str, usuario_id: Optional[int]) -> None:
    """The write already happened at ML: a failure here is logged, never raised."""
    try:
        with get_background_db() as db:
            db.add(
                MlWriteLog(
                    mla=mla,
                    resource=RESOURCE_ITEM,
                    action=_ACTIONS[target],
                    payload={"status": target},
                    usuario_id=usuario_id,
                )
            )
    except Exception as e:
        logger.error(
            "ml_write_log insert failed for mla=%s status=%s (the write at ML is unaffected): %s", mla, target, e
        )


def _enqueue_refresh(mla: str) -> None:
    ml_pub_queue.enqueue(
        [
            ml_pub_queue.EnqueueEntry(
                kind="item", entity_id=mla, lane=ml_pub_queue.LANE_MANUAL, resources=(CORE_RESOURCE,)
            )
        ]
    )


def _enqueue_refresh_safely(mla: str) -> None:
    try:
        _enqueue_refresh(mla)
    except Exception as e:
        logger.error("refresh enqueue failed for mla=%s after a status write: %s", mla, e)
