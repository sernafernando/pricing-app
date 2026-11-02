"""SKU repair: snapshot seller_sku vs ERP codigo for linked publicaciones_ml."""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.publicacion_repair import (
    ACTION_CHANGED,
    ACTION_ERROR,
    ACTION_SKIPPED,
    JOB_SKU,
    TRIGGER_PUBLICATIONS_FULL,
)
from app.services.ml_webhook_client import MLWebhookClient
from app.services.publicacion_repair.envio import latest_snapshots_for_mlas
from app.services.publicacion_repair.tracker import finish_run, record_event, start_run

logger = logging.getLogger(__name__)


def normalize_sku(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def sku_matches_erp(seller_sku: Any, erp_codigo: Any) -> bool:
    left = normalize_sku(seller_sku)
    right = normalize_sku(erp_codigo)
    if left is None or right is None:
        return False
    return left == right


def linked_pubs_with_erp_codigo(db: Session) -> list[tuple[PublicacionML, str]]:
    """Active linked pubs with a non-empty ERP codigo (source of truth for repair)."""
    rows = (
        db.query(PublicacionML, ProductoERP.codigo)
        .join(ProductoERP, ProductoERP.item_id == PublicacionML.item_id)
        .filter(PublicacionML.activo.is_(True))
        .all()
    )
    out: list[tuple[PublicacionML, str]] = []
    for pub, codigo in rows:
        normalized = normalize_sku(codigo)
        if pub.mla and normalized:
            out.append((pub, normalized))
    return out


def seller_sku_payload(erp_codigo: str) -> dict[str, Any]:
    return {"attributes": [{"id": "SELLER_SKU", "value_name": erp_codigo}]}


def _classify_data_write(result: dict[str, Any]) -> tuple[str, Optional[str]]:
    """Return action (changed|skipped|error) and detail."""
    if result.get("ok"):
        return ACTION_CHANGED, None
    if result.get("ambiguous"):
        return ACTION_ERROR, "ambiguous_write"
    body = result.get("body") if isinstance(result.get("body"), dict) else {}
    status = result.get("status_code")
    stamp = body.get("data_write")
    if stamp == "not_attempted" or status in (400, 403, 422):
        detail = body.get("message") or f"http_{status}" if status else "not_attempted"
        return ACTION_SKIPPED, str(detail)[:300]
    detail = body.get("message") or f"http_{status}" if status else "ml_error"
    return ACTION_ERROR, str(detail)[:300]


async def run_sku_repair(
    db: Session,
    *,
    trigger: str = TRIGGER_PUBLICATIONS_FULL,
    client: Optional[MLWebhookClient] = None,
) -> dict[str, int]:
    """Scan linked pubs; PUT SELLER_SKU only when latest snapshot drifts from ERP codigo."""
    run = start_run(db, job_type=JOB_SKU, trigger=trigger)
    scanned = changed = skipped = errors = 0
    fatal: Optional[str] = None

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
        logger.info("sku repair skipped: data write disabled run_id=%s", run.id)
        return {"scanned": 0, "changed": 0, "skipped": 0, "errors": 0}

    ml = client or MLWebhookClient()

    try:
        pubs = linked_pubs_with_erp_codigo(db)
        snaps = latest_snapshots_for_mlas(db, [p.mla for p, _ in pubs])
        scanned = len(pubs)

        for pub, erp_codigo in pubs:
            mla = pub.mla
            snap = snaps.get(mla)
            if snap is None:
                skipped += 1
                record_event(
                    db,
                    run_id=run.id,
                    mla_id=mla,
                    item_id=pub.item_id,
                    action=ACTION_SKIPPED,
                    detail="no_snapshot",
                )
                continue

            before = {"seller_sku": snap.seller_sku, "erp_codigo": erp_codigo}
            if sku_matches_erp(snap.seller_sku, erp_codigo):
                continue

            result = await ml.put_item_data(mla, seller_sku_payload(erp_codigo))
            action, detail = _classify_data_write(result)
            after = {"seller_sku": erp_codigo, "erp_codigo": erp_codigo}
            if action == ACTION_CHANGED:
                changed += 1
            elif action == ACTION_SKIPPED:
                skipped += 1
            else:
                errors += 1
            record_event(
                db,
                run_id=run.id,
                mla_id=mla,
                item_id=pub.item_id,
                action=action,
                before=before,
                after=after,
                detail=detail,
            )
    except Exception as exc:
        fatal = str(exc)[:500]
        logger.exception("sku repair failed run_id=%s", run.id)
        errors += 1

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
        "sku repair done run_id=%s scanned=%s changed=%s skipped=%s errors=%s",
        run.id,
        scanned,
        changed,
        skipped,
        errors,
    )
    return {"scanned": scanned, "changed": changed, "skipped": skipped, "errors": errors}
