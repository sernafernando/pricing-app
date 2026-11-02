"""Envio repair: ME2 + local pickup + colecta/Flex — never free_shipping, never Full."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_publication_snapshot import MLPublicationSnapshot
from app.models.publicacion_ml import PublicacionML
from app.models.publicacion_repair import (
    ACTION_CHANGED,
    ACTION_ERROR,
    ACTION_SKIPPED,
    JOB_ENVIO,
    TRIGGER_PUBLICATIONS_FULL,
)
from app.services.ml_api_client import MercadoLibreAPIClient
from app.services.publicacion_repair import audit as repair_audit
from app.services.publicacion_repair.constants import (
    FLEX_TAG,
    LOGISTIC_COLECTA,
    LOGISTIC_FLEX,
    LOGISTIC_FULL,
    LOGISTIC_LEAVE_ALONE,
    MODE_ME2,
)

logger = logging.getLogger(__name__)

# Keys that must never appear on a repair shipping PUT.
_FORBIDDEN_WRITE_KEYS = frozenset({"free_shipping", "tags", "store_pick_up"})


@dataclass
class EnvioPlan:
    """What to do for one publication. empty plan + skip_reason => no ML writes."""

    skip_reason: Optional[str] = None
    shipping_put: dict[str, Any] = field(default_factory=dict)
    enable_flex: bool = False

    @property
    def needs_write(self) -> bool:
        return bool(self.shipping_put) or self.enable_flex


def shipping_from_snapshot(snap: MLPublicationSnapshot) -> dict[str, Any]:
    tags = snap.shipping_tags
    if isinstance(tags, list):
        tag_list = [str(t) for t in tags if t is not None]
    else:
        tag_list = []
    return {
        "mode": snap.shipping_mode,
        "logistic_type": snap.logistic_type,
        "local_pick_up": snap.local_pick_up,
        "free_shipping": snap.free_shipping,
        "store_pick_up": snap.store_pick_up,
        "tags": tag_list,
    }


def has_flex(current: dict[str, Any]) -> bool:
    tags = current.get("tags") if isinstance(current.get("tags"), list) else []
    if FLEX_TAG in {str(t) for t in tags}:
        return True
    return current.get("logistic_type") == LOGISTIC_FLEX


def has_colecta(current: dict[str, Any]) -> bool:
    return current.get("logistic_type") == LOGISTIC_COLECTA


def is_full(current: dict[str, Any]) -> bool:
    return current.get("logistic_type") == LOGISTIC_FULL


def shipping_incomplete(current: dict[str, Any]) -> bool:
    """Pre-migration / never-hydrated shipping: do not invent a PUT from nulls."""
    return current.get("mode") is None and current.get("logistic_type") is None


def plan_envio_repair(current: dict[str, Any]) -> EnvioPlan:
    """Decide ML writes. Never touches free_shipping; never writes Full."""
    if is_full(current):
        return EnvioPlan(skip_reason="full_fulfillment")
    if shipping_incomplete(current):
        return EnvioPlan(skip_reason="incomplete_snapshot")

    put: dict[str, Any] = {}
    if current.get("mode") != MODE_ME2:
        put["mode"] = MODE_ME2
    if current.get("local_pick_up") is not True:
        put["local_pick_up"] = True

    logistic = current.get("logistic_type")
    if not has_colecta(current) and logistic not in LOGISTIC_LEAVE_ALONE:
        # Missing colecta and not Flex/Places/Full primary — set cross_docking.
        put["logistic_type"] = LOGISTIC_COLECTA

    for key in _FORBIDDEN_WRITE_KEYS:
        put.pop(key, None)

    return EnvioPlan(
        shipping_put=put,
        enable_flex=not has_flex(current),
    )


def sanitize_shipping_put(shipping: dict[str, Any]) -> dict[str, Any]:
    """Drop forbidden keys even if a caller passes them by mistake."""
    return {k: v for k, v in shipping.items() if k not in _FORBIDDEN_WRITE_KEYS and v is not None}


def latest_snapshots_for_mlas(db: Session, mlas: list[str]) -> dict[str, MLPublicationSnapshot]:
    if not mlas:
        return {}
    max_dates = (
        db.query(
            MLPublicationSnapshot.mla_id,
            func.max(MLPublicationSnapshot.snapshot_date).label("max_date"),
        )
        .filter(MLPublicationSnapshot.mla_id.in_(mlas))
        .group_by(MLPublicationSnapshot.mla_id)
        .subquery()
    )
    rows = (
        db.query(MLPublicationSnapshot)
        .join(
            max_dates,
            (MLPublicationSnapshot.mla_id == max_dates.c.mla_id)
            & (MLPublicationSnapshot.snapshot_date == max_dates.c.max_date),
        )
        .all()
    )
    return {row.mla_id: row for row in rows}


def linked_publicaciones(db: Session) -> list[PublicacionML]:
    return db.query(PublicacionML).filter(PublicacionML.activo.is_(True)).all()


def _load_work_items(db: Session) -> list[tuple[str, Optional[int], Optional[dict[str, Any]]]]:
    """Return (mla, item_id, shipping_dict|None) and leave no open write tx."""
    pubs = linked_publicaciones(db)
    mlas = [p.mla for p in pubs if p.mla]
    snaps = latest_snapshots_for_mlas(db, mlas)
    items: list[tuple[str, Optional[int], Optional[dict[str, Any]]]] = []
    for pub in pubs:
        if not pub.mla:
            continue
        snap = snaps.get(pub.mla)
        before = shipping_from_snapshot(snap) if snap is not None else None
        items.append((pub.mla, pub.item_id, before))
    return items


async def run_envio_repair(
    db: Session,
    *,
    trigger: str = TRIGGER_PUBLICATIONS_FULL,
    client: Optional[MercadoLibreAPIClient] = None,
    max_writes: int = repair_audit.DEFAULT_MAX_WRITES_PER_RUN,
    pacing_seconds: float = repair_audit.DEFAULT_WRITE_PACING_SECONDS,
) -> dict[str, int]:
    """Repair ME2/colecta/Flex/local_pick_up for linked pubs. Never free_shipping / Full.

    `db` is used only for the initial read; tracker/write-log use short background sessions
    so ML HTTP never runs inside an open Pricing transaction.
    """
    run = repair_audit.start_run_bg(job_type=JOB_ENVIO, trigger=trigger)
    scanned = changed = skipped = errors = 0
    writes_done = 0
    fatal: Optional[str] = None

    if settings.ML_PUB_KILL_SWITCH:
        repair_audit.finish_run_bg(
            run, scanned=0, changed=0, skipped=0, errors=0, error_message="ML_PUB_KILL_SWITCH=true"
        )
        return {"scanned": 0, "changed": 0, "skipped": 0, "errors": 0}

    if not settings.ML_ITEM_DATA_WRITE_ENABLED:
        repair_audit.finish_run_bg(
            run,
            scanned=0,
            changed=0,
            skipped=0,
            errors=0,
            error_message="ML_ITEM_DATA_WRITE_ENABLED=false",
        )
        return {"scanned": 0, "changed": 0, "skipped": 0, "errors": 0}

    ml = client or MercadoLibreAPIClient()

    try:
        # Prefer a dedicated read session when caller passed the long-lived sync db.
        with get_background_db() as read_db:
            work = _load_work_items(read_db)
        scanned = len(work)

        for mla, item_id, before in work:
            if before is None:
                skipped += 1
                repair_audit.record_event_bg(
                    run_id=run.id,
                    mla_id=mla,
                    item_id=item_id,
                    action=ACTION_SKIPPED,
                    detail="no_snapshot",
                )
                continue

            plan = plan_envio_repair(before)
            if plan.skip_reason:
                skipped += 1
                repair_audit.record_event_bg(
                    run_id=run.id,
                    mla_id=mla,
                    item_id=item_id,
                    action=ACTION_SKIPPED,
                    before=before,
                    detail=plan.skip_reason,
                )
                continue
            if not plan.needs_write:
                continue
            if writes_done >= max_writes:
                skipped += 1
                repair_audit.record_event_bg(
                    run_id=run.id,
                    mla_id=mla,
                    item_id=item_id,
                    action=ACTION_SKIPPED,
                    before=before,
                    detail="max_writes_cap",
                )
                continue

            after: dict[str, Any] = {"shipping_put": plan.shipping_put, "enable_flex": plan.enable_flex}
            details: list[str] = []

            if plan.shipping_put:
                payload = sanitize_shipping_put(plan.shipping_put)
                if "free_shipping" in payload or "tags" in payload:
                    raise RuntimeError("forbidden shipping keys leaked into PUT payload")
                result = await ml.put_item_shipping(mla, payload)
                if result.ok:
                    details.append("shipping_put")
                    repair_audit.after_shipping_changed(mla, payload)
                elif result.not_allowed:
                    skipped += 1
                    repair_audit.record_event_bg(
                        run_id=run.id,
                        mla_id=mla,
                        item_id=item_id,
                        action=ACTION_SKIPPED,
                        before=before,
                        after=after,
                        detail=result.detail or "ml_not_allowed",
                    )
                    continue
                else:
                    errors += 1
                    repair_audit.record_event_bg(
                        run_id=run.id,
                        mla_id=mla,
                        item_id=item_id,
                        action=ACTION_ERROR,
                        before=before,
                        after=after,
                        detail=result.detail or "ml_error",
                    )
                    continue

            if plan.enable_flex:
                flex = await ml.enable_item_flex(mla)
                if flex.ok:
                    details.append("flex_enabled")
                    repair_audit.after_flex_enabled(mla)
                elif flex.not_allowed:
                    skipped += 1
                    repair_audit.record_event_bg(
                        run_id=run.id,
                        mla_id=mla,
                        item_id=item_id,
                        action=ACTION_SKIPPED,
                        before=before,
                        after=after,
                        detail=flex.detail or "flex_not_allowed",
                    )
                    continue
                else:
                    errors += 1
                    repair_audit.record_event_bg(
                        run_id=run.id,
                        mla_id=mla,
                        item_id=item_id,
                        action=ACTION_ERROR,
                        before=before,
                        after=after,
                        detail=flex.detail or "flex_error",
                    )
                    continue

            changed += 1
            writes_done += 1
            repair_audit.record_event_bg(
                run_id=run.id,
                mla_id=mla,
                item_id=item_id,
                action=ACTION_CHANGED,
                before=before,
                after=after,
                detail=",".join(details) or None,
            )
            if pacing_seconds > 0:
                await asyncio.sleep(pacing_seconds)
    except Exception as exc:
        fatal = str(exc)[:500]
        logger.exception("envio repair failed run_id=%s", run.id)
        errors += 1

    repair_audit.finish_run_bg(
        run,
        scanned=scanned,
        changed=changed,
        skipped=skipped,
        errors=errors,
        error_message=fatal,
    )
    logger.info(
        "envio repair done run_id=%s scanned=%s changed=%s skipped=%s errors=%s",
        run.id,
        scanned,
        changed,
        skipped,
        errors,
    )
    return {"scanned": scanned, "changed": changed, "skipped": skipped, "errors": errors}
