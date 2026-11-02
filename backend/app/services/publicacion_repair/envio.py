"""Envio repair: ME2 + local pickup + colecta/Flex — never free_shipping, never Full."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
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
from app.services.publicacion_repair.constants import (
    FLEX_TAG,
    LOGISTIC_COLECTA,
    LOGISTIC_FLEX,
    LOGISTIC_FULL,
    LOGISTIC_LEAVE_ALONE,
    MODE_ME2,
)
from app.services.publicacion_repair.tracker import finish_run, record_event, start_run

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


def _safe_record(db: Session, **kwargs: Any) -> None:
    try:
        record_event(db, **kwargs)
    except Exception:
        logger.exception("repair event insert failed mla=%s", kwargs.get("mla_id"))
        try:
            db.rollback()
        except Exception:
            logger.exception("rollback after event failure failed")


async def run_envio_repair(
    db: Session,
    *,
    trigger: str = TRIGGER_PUBLICATIONS_FULL,
    client: Optional[MercadoLibreAPIClient] = None,
) -> dict[str, int]:
    """Repair ME2/colecta/Flex/local_pick_up for linked pubs. Never free_shipping / Full."""
    run = start_run(db, job_type=JOB_ENVIO, trigger=trigger)
    scanned = changed = skipped = errors = 0
    fatal: Optional[str] = None

    if settings.ML_PUB_KILL_SWITCH:
        finish_run(
            db,
            run,
            scanned=0,
            changed=0,
            skipped=0,
            errors=0,
            error_message="ML_PUB_KILL_SWITCH=true",
        )
        return {"scanned": 0, "changed": 0, "skipped": 0, "errors": 0}

    if not settings.ML_ITEM_DATA_WRITE_ENABLED:
        finish_run(
            db,
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
        pubs = linked_publicaciones(db)
        mlas = [p.mla for p in pubs if p.mla]
        snaps = latest_snapshots_for_mlas(db, mlas)
        scanned = len(pubs)
        # Release the read snapshot before HTTP writes (avoid long-held tx).
        db.commit()

        for pub in pubs:
            mla = pub.mla
            snap = snaps.get(mla)
            if snap is None:
                skipped += 1
                _safe_record(
                    db,
                    run_id=run.id,
                    mla_id=mla,
                    item_id=pub.item_id,
                    action=ACTION_SKIPPED,
                    detail="no_snapshot",
                )
                continue

            before = shipping_from_snapshot(snap)
            plan = plan_envio_repair(before)
            if plan.skip_reason:
                skipped += 1
                _safe_record(
                    db,
                    run_id=run.id,
                    mla_id=mla,
                    item_id=pub.item_id,
                    action=ACTION_SKIPPED,
                    before=before,
                    detail=plan.skip_reason,
                )
                continue
            if not plan.needs_write:
                continue

            after: dict[str, Any] = {"shipping_put": plan.shipping_put, "enable_flex": plan.enable_flex}
            write_ok = True
            details: list[str] = []

            if plan.shipping_put:
                payload = sanitize_shipping_put(plan.shipping_put)
                assert "free_shipping" not in payload
                assert "tags" not in payload
                result = await ml.put_item_shipping(mla, payload)
                if result.ok:
                    details.append("shipping_put")
                elif result.not_allowed:
                    write_ok = False
                    skipped += 1
                    _safe_record(
                        db,
                        run_id=run.id,
                        mla_id=mla,
                        item_id=pub.item_id,
                        action=ACTION_SKIPPED,
                        before=before,
                        after=after,
                        detail=result.detail or "ml_not_allowed",
                    )
                    continue
                else:
                    write_ok = False
                    errors += 1
                    _safe_record(
                        db,
                        run_id=run.id,
                        mla_id=mla,
                        item_id=pub.item_id,
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
                elif flex.not_allowed:
                    write_ok = False
                    skipped += 1
                    _safe_record(
                        db,
                        run_id=run.id,
                        mla_id=mla,
                        item_id=pub.item_id,
                        action=ACTION_SKIPPED,
                        before=before,
                        after=after,
                        detail=flex.detail or "flex_not_allowed",
                    )
                    continue
                else:
                    write_ok = False
                    errors += 1
                    _safe_record(
                        db,
                        run_id=run.id,
                        mla_id=mla,
                        item_id=pub.item_id,
                        action=ACTION_ERROR,
                        before=before,
                        after=after,
                        detail=flex.detail or "flex_error",
                    )
                    continue

            if write_ok:
                changed += 1
                _safe_record(
                    db,
                    run_id=run.id,
                    mla_id=mla,
                    item_id=pub.item_id,
                    action=ACTION_CHANGED,
                    before=before,
                    after=after,
                    detail=",".join(details) or None,
                )
    except Exception as exc:
        fatal = str(exc)[:500]
        logger.exception("envio repair failed run_id=%s", run.id)
        errors += 1
        try:
            db.rollback()
        except Exception:
            logger.exception("rollback after envio repair failure failed")

    finish_run(
        db,
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
