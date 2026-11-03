"""start_run / finish_run / record_event for publicacion repair jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.publicacion_repair import (
    ACTION_CHANGED,
    ACTION_ERROR,
    ACTION_SKIPPED,
    PublicacionRepairEvent,
    PublicacionRepairRun,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_RUNNING,
    STATUS_SUCCESS,
)


def start_run(db: Session, *, job_type: str, trigger: str) -> PublicacionRepairRun:
    run = PublicacionRepairRun(
        job_type=job_type,
        status=STATUS_RUNNING,
        trigger=trigger,
        scanned=0,
        changed=0,
        skipped=0,
        errors=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_run(
    db: Session,
    run: PublicacionRepairRun,
    *,
    scanned: int,
    changed: int,
    skipped: int,
    errors: int,
    error_message: Optional[str] = None,
) -> PublicacionRepairRun:
    run.scanned = scanned
    run.changed = changed
    run.skipped = skipped
    run.errors = errors
    run.error_message = error_message
    run.finished_at = datetime.now(UTC)
    if error_message and scanned == 0:
        run.status = STATUS_FAILED
    elif errors == 0:
        run.status = STATUS_SUCCESS
    elif changed > 0:
        run.status = STATUS_PARTIAL
    else:
        run.status = STATUS_PARTIAL if scanned > 0 else STATUS_FAILED
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _jsonable(value: Any) -> Any:
    """Make values safe for JSONB (envio `before` carries raw `fetched_at` datetimes)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def record_event(
    db: Session,
    *,
    run_id: int,
    mla_id: str,
    action: str,
    item_id: Optional[int] = None,
    before: Optional[dict[str, Any]] = None,
    after: Optional[dict[str, Any]] = None,
    detail: Optional[str] = None,
) -> PublicacionRepairEvent:
    if action not in (ACTION_CHANGED, ACTION_SKIPPED, ACTION_ERROR):
        raise ValueError(f"invalid repair action: {action}")
    event = PublicacionRepairEvent(
        run_id=run_id,
        mla_id=mla_id,
        item_id=item_id,
        action=action,
        before=_jsonable(before) if before is not None else None,
        after=_jsonable(after) if after is not None else None,
        detail=detail,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
