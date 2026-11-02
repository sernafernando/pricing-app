"""Envio repair: ME2 + local pickup + colecta/Flex — never free_shipping, never Full.

Triggered by a background tick (free_shipping-style), not by sync_ml_publications_full.
Condition: active linked pubs × ml_items drift vs the write policy below.
"""

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
from app.models.ml_publications import MlItem
from app.models.publicacion_ml import PublicacionML
from app.models.publicacion_repair import (
    ACTION_CHANGED,
    ACTION_ERROR,
    ACTION_SKIPPED,
    JOB_ENVIO,
    TRIGGER_TICK,
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

# Same gate as override push: only statuses ML lets us edit.
MODIFIABLE_STATUSES = frozenset({"active", "paused"})

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
    """Legacy helper for tests / older callers; production reads ml_items."""
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
        "status": "active",
    }


def shipping_from_ml_item(item: MlItem) -> dict[str, Any]:
    """Current shipping view from the publications store (columns + raw.shipping)."""
    raw = item.raw if isinstance(item.raw, dict) else {}
    ship = raw.get("shipping") if isinstance(raw.get("shipping"), dict) else {}
    tags = ship.get("tags")
    tag_list = [str(t) for t in tags if t is not None] if isinstance(tags, list) else []
    mode = item.shipping_mode if item.shipping_mode is not None else ship.get("mode")
    logistic = item.logistic_type if item.logistic_type is not None else ship.get("logistic_type")
    free_shipping = item.free_shipping if item.free_shipping is not None else ship.get("free_shipping")
    return {
        "mode": mode,
        "logistic_type": logistic,
        "local_pick_up": ship.get("local_pick_up"),
        "free_shipping": free_shipping,
        "store_pick_up": ship.get("store_pick_up"),
        "tags": tag_list,
        "status": item.status,
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
    """Never-hydrated shipping: do not invent a PUT from nulls."""
    return current.get("mode") is None and current.get("logistic_type") is None


def plan_envio_repair(current: dict[str, Any]) -> EnvioPlan:
    """Decide ML writes. Never touches free_shipping; never writes Full."""
    status = current.get("status")
    if status is not None and status not in MODIFIABLE_STATUSES:
        return EnvioPlan(skip_reason="status_not_modifiable")
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
    """Kept for SKU repair / tests that still contrast snapshots."""
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


def _load_work_items(db: Session) -> list[tuple[str, Optional[int], dict[str, Any]]]:
    """Linked active pubs joined to ml_items → (mla, erp_item_id, shipping_dict)."""
    rows = (
        db.query(PublicacionML, MlItem)
        .join(MlItem, MlItem.item_id == PublicacionML.mla)
        .filter(PublicacionML.activo.is_(True))
        .filter(MlItem.gone_at.is_(None))
        .all()
    )
    items: list[tuple[str, Optional[int], dict[str, Any]]] = []
    for pub, ml_item in rows:
        if not pub.mla:
            continue
        items.append((pub.mla, pub.item_id, shipping_from_ml_item(ml_item)))
    return items


async def run_envio_repair(
    db: Optional[Session] = None,
    *,
    trigger: str = TRIGGER_TICK,
    client: Optional[MercadoLibreAPIClient] = None,
    max_writes: int = repair_audit.DEFAULT_MAX_WRITES_PER_RUN,
    pacing_seconds: float = repair_audit.DEFAULT_WRITE_PACING_SECONDS,
) -> dict[str, int]:
    """Repair ME2/colecta/Flex/local_pick_up for linked pubs. Never free_shipping / Full.

    `db` is ignored (kept for call-site compat); all DB work uses short background sessions
    so ML HTTP never runs inside an open Pricing transaction.
    """
    del db  # explicit: do not pin a caller session across HTTP
    run_id = repair_audit.start_run_bg(job_type=JOB_ENVIO, trigger=trigger)
    scanned = changed = skipped = errors = 0
    writes_done = 0
    fatal: Optional[str] = None

    if settings.ML_PUB_KILL_SWITCH:
        repair_audit.finish_run_bg(
            run_id, scanned=0, changed=0, skipped=0, errors=0, error_message="ML_PUB_KILL_SWITCH=true"
        )
        return {"scanned": 0, "changed": 0, "skipped": 0, "errors": 0}

    if not settings.ML_ITEM_DATA_WRITE_ENABLED:
        repair_audit.finish_run_bg(
            run_id,
            scanned=0,
            changed=0,
            skipped=0,
            errors=0,
            error_message="ML_ITEM_DATA_WRITE_ENABLED=false",
        )
        return {"scanned": 0, "changed": 0, "skipped": 0, "errors": 0}

    ml = client or MercadoLibreAPIClient()

    try:
        with get_background_db() as read_db:
            work = _load_work_items(read_db)
        scanned = len(work)

        for mla, item_id, before in work:
            plan = plan_envio_repair(before)
            if plan.skip_reason:
                skipped += 1
                repair_audit.record_event_bg(
                    run_id=run_id,
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
                    run_id=run_id,
                    mla_id=mla,
                    item_id=item_id,
                    action=ACTION_SKIPPED,
                    before=before,
                    detail="max_writes_cap",
                )
                continue

            # Count every item we attempt to write (success or ML refusal), not only full success.
            writes_done += 1
            after: dict[str, Any] = {"shipping_put": plan.shipping_put, "enable_flex": plan.enable_flex}
            details: list[str] = []
            item_failed = False

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
                    item_failed = True
                    repair_audit.record_event_bg(
                        run_id=run_id,
                        mla_id=mla,
                        item_id=item_id,
                        action=ACTION_SKIPPED,
                        before=before,
                        after=after,
                        detail=result.detail or "ml_not_allowed",
                    )
                else:
                    errors += 1
                    item_failed = True
                    repair_audit.record_event_bg(
                        run_id=run_id,
                        mla_id=mla,
                        item_id=item_id,
                        action=ACTION_ERROR,
                        before=before,
                        after=after,
                        detail=result.detail or "ml_error",
                    )

            if item_failed:
                if pacing_seconds > 0:
                    await asyncio.sleep(pacing_seconds)
                continue

            if plan.enable_flex:
                flex = await ml.enable_item_flex(mla)
                if flex.ok:
                    details.append("flex_enabled")
                    repair_audit.after_flex_enabled(mla)
                elif flex.not_allowed:
                    skipped += 1
                    repair_audit.record_event_bg(
                        run_id=run_id,
                        mla_id=mla,
                        item_id=item_id,
                        action=ACTION_SKIPPED,
                        before=before,
                        after=after,
                        detail=flex.detail or "flex_not_allowed",
                    )
                    if pacing_seconds > 0:
                        await asyncio.sleep(pacing_seconds)
                    continue
                else:
                    errors += 1
                    repair_audit.record_event_bg(
                        run_id=run_id,
                        mla_id=mla,
                        item_id=item_id,
                        action=ACTION_ERROR,
                        before=before,
                        after=after,
                        detail=flex.detail or "flex_error",
                    )
                    if pacing_seconds > 0:
                        await asyncio.sleep(pacing_seconds)
                    continue

            changed += 1
            repair_audit.record_event_bg(
                run_id=run_id,
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
        logger.exception("envio repair failed run_id=%s", run_id)
        errors += 1

    repair_audit.finish_run_bg(
        run_id,
        scanned=scanned,
        changed=changed,
        skipped=skipped,
        errors=errors,
        error_message=fatal,
    )
    logger.info(
        "envio repair done run_id=%s scanned=%s changed=%s skipped=%s errors=%s",
        run_id,
        scanned,
        changed,
        skipped,
        errors,
    )
    return {"scanned": scanned, "changed": changed, "skipped": skipped, "errors": errors}
