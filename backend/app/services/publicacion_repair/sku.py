"""SKU repair: ml_items.seller_sku vs ERP codigo for linked publicaciones_ml.

Triggered by a background tick (free_shipping-style), not by sync_ml_publications_full.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_publications import MlItem, MlItemVariation
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.publicacion_repair import (
    ACTION_CHANGED,
    ACTION_ERROR,
    ACTION_SKIPPED,
    JOB_SKU,
    TRIGGER_TICK,
)
from app.models.ml_write_log import ACTION_UPDATE_DATA
from app.services.ml_webhook_client import MLWebhookClient
from app.services.publicacion_repair import audit as repair_audit
from app.services.publicacion_repair.envio import MODIFIABLE_STATUSES, is_ml_item_stale

logger = logging.getLogger(__name__)

DETAIL_HAS_VARIATIONS = "has_variations"
# Successful SELLER_SKU PUT — motive is SKU drift vs ERP (see before/after).
DETAIL_SELLER_SKU = "seller_sku"


def normalize_sku(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def sku_matches_erp(seller_sku: Any, erp_codigo: Any) -> bool:
    """True only when both sides match after strip. Separator-only diffs are mismatches.

    Repair must not use links.normalize_sku: published SELLER_SKU should equal GBP codigo.
    """
    left = normalize_sku(seller_sku)
    right = normalize_sku(erp_codigo)
    if left is None or right is None:
        return False
    return left == right


def seller_sku_payload(erp_codigo: str) -> dict[str, Any]:
    return {"attributes": [{"id": "SELLER_SKU", "value_name": erp_codigo}]}


def _classify_data_write(result: dict[str, Any]) -> tuple[str, Optional[str]]:
    """Return action (changed|skipped|error) and detail."""
    if result.get("ok"):
        return ACTION_CHANGED, DETAIL_SELLER_SKU
    if result.get("ambiguous"):
        return ACTION_ERROR, "ambiguous_write"
    body = result.get("body") if isinstance(result.get("body"), dict) else {}
    status = result.get("status_code")
    stamp = body.get("data_write")
    if stamp == "not_attempted" or status in (400, 403, 422):
        detail = body.get("message") or (f"http_{status}" if status else "not_attempted")
        return ACTION_SKIPPED, str(detail)[:300]
    detail = body.get("message") or (f"http_{status}" if status else "ml_error")
    return ACTION_ERROR, str(detail)[:300]


def mlas_with_live_variations(db: Session, mlas: list[str]) -> set[str]:
    """MLA ids that still have at least one non-gone ml_item_variations row."""
    if not mlas:
        return set()
    rows = (
        db.query(MlItemVariation.item_id)
        .filter(MlItemVariation.item_id.in_(mlas))
        .filter(MlItemVariation.gone_at.is_(None))
        .distinct()
        .all()
    )
    return {str(item_id) for (item_id,) in rows if item_id}


def _load_work_items(
    db: Session,
) -> list[tuple[str, Optional[int], Optional[str], str, Optional[str], Any]]:
    """Return (mla, item_id, ml_seller_sku, erp_codigo, status, fetched_at) for linked pubs.

    Linked means `publicaciones_ml.item_id` is set (ERP link); unlinked rows are excluded.
    """
    rows = (
        db.query(
            PublicacionML,
            ProductoERP.codigo,
            MlItem.seller_sku,
            MlItem.status,
            MlItem.fetched_at,
        )
        .join(ProductoERP, ProductoERP.item_id == PublicacionML.item_id)
        .join(MlItem, MlItem.item_id == PublicacionML.mla)
        .filter(PublicacionML.activo.is_(True))
        .filter(PublicacionML.item_id.isnot(None))
        .filter(MlItem.gone_at.is_(None))
        .all()
    )
    out: list[tuple[str, Optional[int], Optional[str], str, Optional[str], Any]] = []
    for pub, codigo, seller_sku, status, fetched_at in rows:
        normalized = normalize_sku(codigo)
        if pub.mla and normalized:
            out.append((pub.mla, pub.item_id, seller_sku, normalized, status, fetched_at))
    return out


async def run_sku_repair(
    db: Optional[Session] = None,
    *,
    trigger: str = TRIGGER_TICK,
    client: Optional[MLWebhookClient] = None,
    max_writes: int = repair_audit.DEFAULT_MAX_WRITES_PER_RUN,
    pacing_seconds: float = repair_audit.DEFAULT_WRITE_PACING_SECONDS,
    before_write: Optional[Callable[[], bool]] = None,
    on_rate_limited: Optional[Callable[[Optional[str]], None]] = None,
) -> dict[str, int]:
    """Scan linked pubs; PUT SELLER_SKU when ml_items.seller_sku drifts from ERP codigo.

    On HTTP 429: call `on_rate_limited` with Retry-After (if any) and stop the run so the
    shared worker Pacer can AIMD instead of walking the rest of the tick.
    """
    del db
    run_id = repair_audit.start_run_bg(job_type=JOB_SKU, trigger=trigger)
    scanned = changed = skipped = errors = 0
    writes_done = 0
    fatal: Optional[str] = None

    if settings.ML_PUB_KILL_SWITCH:
        repair_audit.finish_run_bg(
            run_id,
            scanned=0,
            changed=0,
            skipped=0,
            errors=0,
            error_message="ML_PUB_KILL_SWITCH=true",
        )
        logger.info("sku repair skipped: kill switch run_id=%s", run_id)
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
        logger.info("sku repair skipped: data write disabled run_id=%s", run_id)
        return {"scanned": 0, "changed": 0, "skipped": 0, "errors": 0}

    ml = client or MLWebhookClient()

    try:
        with get_background_db() as read_db:
            work = _load_work_items(read_db)
            variation_mlas = mlas_with_live_variations(read_db, [mla for mla, *_ in work])
        scanned = len(work)

        for mla, item_id, seller_sku, erp_codigo, status, fetched_at in work:
            before = {
                "seller_sku": seller_sku,
                "erp_codigo": erp_codigo,
                "status": status,
                "fetched_at": fetched_at.isoformat() if hasattr(fetched_at, "isoformat") else fetched_at,
            }
            if status is not None and status not in MODIFIABLE_STATUSES:
                skipped += 1
                repair_audit.record_event_bg(
                    run_id=run_id,
                    mla_id=mla,
                    item_id=item_id,
                    action=ACTION_SKIPPED,
                    before=before,
                    detail="status_not_modifiable",
                )
                continue
            if is_ml_item_stale(fetched_at):
                skipped += 1
                repair_audit.record_event_bg(
                    run_id=run_id,
                    mla_id=mla,
                    item_id=item_id,
                    action=ACTION_SKIPPED,
                    before=before,
                    detail="stale_ml_item",
                )
                continue
            if mla in variation_mlas:
                # Item-level SELLER_SKU PUT is wrong when the listing has live variations.
                skipped += 1
                repair_audit.record_event_bg(
                    run_id=run_id,
                    mla_id=mla,
                    item_id=item_id,
                    action=ACTION_SKIPPED,
                    before=before,
                    detail=DETAIL_HAS_VARIATIONS,
                )
                continue
            if sku_matches_erp(seller_sku, erp_codigo):
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
            if before_write is not None and not before_write():
                skipped += 1
                repair_audit.record_event_bg(
                    run_id=run_id,
                    mla_id=mla,
                    item_id=item_id,
                    action=ACTION_SKIPPED,
                    before=before,
                    detail="pacer_deadline",
                )
                break

            writes_done += 1
            result = await ml.put_item_data(mla, seller_sku_payload(erp_codigo))
            after = {"seller_sku": erp_codigo, "erp_codigo": erp_codigo}
            if result.get("status_code") == 429:
                if on_rate_limited is not None:
                    retry_after = result.get("retry_after")
                    on_rate_limited(retry_after if isinstance(retry_after, str) else None)
                errors += 1
                repair_audit.record_event_bg(
                    run_id=run_id,
                    mla_id=mla,
                    item_id=item_id,
                    action=ACTION_ERROR,
                    before=before,
                    after=after,
                    detail="rate_limited",
                )
                break

            action, detail = _classify_data_write(result)
            if action == ACTION_CHANGED:
                changed += 1
                repair_audit.record_ml_write_log(
                    mla,
                    ACTION_UPDATE_DATA,
                    {"attributes": [{"id": "SELLER_SKU", "value_name": erp_codigo}]},
                )
                repair_audit.enqueue_item_refresh_safely(mla)
            elif action == ACTION_SKIPPED:
                skipped += 1
            else:
                errors += 1
            repair_audit.record_event_bg(
                run_id=run_id,
                mla_id=mla,
                item_id=item_id,
                action=action,
                before=before,
                after=after,
                detail=detail,
            )
            if pacing_seconds > 0:
                await asyncio.sleep(pacing_seconds)
    except Exception as exc:
        fatal = str(exc)[:500]
        logger.exception("sku repair failed run_id=%s", run_id)
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
        "sku repair done run_id=%s scanned=%s changed=%s skipped=%s errors=%s",
        run_id,
        scanned,
        changed,
        skipped,
        errors,
    )
    return {"scanned": scanned, "changed": changed, "skipped": skipped, "errors": errors}
