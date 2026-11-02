"""Envio repair: drift from latest snapshots vs ENVIO_TARGET; PUT only failures."""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

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
from app.services.publicacion_repair.constants import ENVIO_TARGET, ENVIO_TARGET_TAGS
from app.services.publicacion_repair.tracker import finish_run, record_event, start_run

logger = logging.getLogger(__name__)


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


def tags_match(actual: Any, expected: tuple[str, ...] = ENVIO_TARGET_TAGS) -> bool:
    if not isinstance(actual, list):
        return False
    return {str(t) for t in actual if t is not None} == set(expected)


def shipping_matches_target(current: dict[str, Any], target: dict[str, Any] = ENVIO_TARGET) -> bool:
    if current.get("mode") != target["mode"]:
        return False
    if current.get("logistic_type") != target["logistic_type"]:
        return False
    if current.get("local_pick_up") is not True:
        return False
    if current.get("free_shipping") is not True:
        return False
    if current.get("store_pick_up") is not False:
        return False
    return tags_match(current.get("tags"), tuple(target["tags"]))


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


def ml_shipping_payload(target: dict[str, Any] = ENVIO_TARGET) -> dict[str, Any]:
    """Body fields sent to ML. Tags included; if ML rejects, caller records error/skip."""
    return {
        "mode": target["mode"],
        "logistic_type": target["logistic_type"],
        "local_pick_up": target["local_pick_up"],
        "free_shipping": target["free_shipping"],
        "store_pick_up": target["store_pick_up"],
        "tags": list(target["tags"]),
    }


async def run_envio_repair(
    db: Session,
    *,
    trigger: str = TRIGGER_PUBLICATIONS_FULL,
    client: Optional[MercadoLibreAPIClient] = None,
) -> dict[str, int]:
    """Scan linked pubs; PUT shipping only when latest snapshot drifts from ENVIO_TARGET."""
    run = start_run(db, job_type=JOB_ENVIO, trigger=trigger)
    scanned = changed = skipped = errors = 0
    fatal: Optional[str] = None
    ml = client or MercadoLibreAPIClient()

    try:
        pubs = linked_publicaciones(db)
        mlas = [p.mla for p in pubs if p.mla]
        snaps = latest_snapshots_for_mlas(db, mlas)
        scanned = len(pubs)

        for pub in pubs:
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

            before = shipping_from_snapshot(snap)
            if shipping_matches_target(before):
                continue

            result = await ml.put_item_shipping(mla, ml_shipping_payload())
            if result.ok:
                changed += 1
                record_event(
                    db,
                    run_id=run.id,
                    mla_id=mla,
                    item_id=pub.item_id,
                    action=ACTION_CHANGED,
                    before=before,
                    after=ml_shipping_payload(),
                    detail=None,
                )
            elif result.not_allowed:
                skipped += 1
                record_event(
                    db,
                    run_id=run.id,
                    mla_id=mla,
                    item_id=pub.item_id,
                    action=ACTION_SKIPPED,
                    before=before,
                    after=ml_shipping_payload(),
                    detail=result.detail or "ml_not_allowed",
                )
            else:
                errors += 1
                record_event(
                    db,
                    run_id=run.id,
                    mla_id=mla,
                    item_id=pub.item_id,
                    action=ACTION_ERROR,
                    before=before,
                    after=ml_shipping_payload(),
                    detail=result.detail or "ml_error",
                )
    except Exception as exc:
        fatal = str(exc)[:500]
        logger.exception("envio repair failed run_id=%s", run.id)
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
        "envio repair done run_id=%s scanned=%s changed=%s skipped=%s errors=%s",
        run.id,
        scanned,
        changed,
        skipped,
        errors,
    )
    return {"scanned": scanned, "changed": changed, "skipped": skipped, "errors": errors}
