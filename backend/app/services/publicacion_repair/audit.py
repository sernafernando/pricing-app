"""Short-lived DB + queue side effects after a confirmed ML repair write."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.database import get_background_db
from app.models.ml_write_log import (
    ACTION_ENABLE_FLEX,
    ACTION_UPDATE_SHIPPING,
    RESOURCE_ITEM,
    MlWriteLog,
)
from app.models.publicacion_repair import PublicacionRepairRun
from app.services.ml_publications import queue as ml_pub_queue
from app.services.ml_publications.resources import CORE_RESOURCE
from app.services.publicacion_repair.tracker import finish_run, record_event, start_run

logger = logging.getLogger(__name__)

# Soft cap per sync_full run so a bad night cannot fan out unbounded PUTs.
DEFAULT_MAX_WRITES_PER_RUN = 200
DEFAULT_WRITE_PACING_SECONDS = 0.15


def start_run_bg(*, job_type: str, trigger: str) -> PublicacionRepairRun:
    with get_background_db() as db:
        return start_run(db, job_type=job_type, trigger=trigger)


def finish_run_bg(run: PublicacionRepairRun, **kwargs: Any) -> PublicacionRepairRun:
    with get_background_db() as db:
        attached = db.get(PublicacionRepairRun, run.id)
        if attached is None:
            logger.error("repair run %s missing at finish", run.id)
            return run
        return finish_run(db, attached, **kwargs)


def record_event_bg(**kwargs: Any) -> None:
    try:
        with get_background_db() as db:
            record_event(db, **kwargs)
    except Exception:
        logger.exception("repair event insert failed mla=%s", kwargs.get("mla_id"))


def record_ml_write_log(mla: str, action: str, payload: Optional[dict[str, Any]]) -> None:
    try:
        with get_background_db() as db:
            db.add(
                MlWriteLog(
                    mla=mla[:32],
                    resource=RESOURCE_ITEM,
                    action=action,
                    payload=payload,
                    usuario_id=None,
                )
            )
    except Exception as e:
        logger.error("ml_write_log insert failed for mla=%s action=%s: %s", mla, action, e)


def enqueue_item_refresh_safely(mla: str) -> None:
    try:
        ml_pub_queue.enqueue(
            [
                ml_pub_queue.EnqueueEntry(
                    kind="item",
                    entity_id=mla,
                    lane=ml_pub_queue.LANE_MANUAL,
                    resources=(CORE_RESOURCE,),
                )
            ]
        )
    except Exception as e:
        logger.error("refresh enqueue failed for mla=%s after repair write: %s", mla, e)


def after_shipping_changed(mla: str, shipping_put: dict[str, Any]) -> None:
    record_ml_write_log(mla, ACTION_UPDATE_SHIPPING, {"shipping": shipping_put})
    enqueue_item_refresh_safely(mla)


def after_flex_enabled(mla: str) -> None:
    record_ml_write_log(mla, ACTION_ENABLE_FLEX, {"site": "MLA"})
    enqueue_item_refresh_safely(mla)
