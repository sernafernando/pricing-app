"""
Enqueue, claim, reuse, retry, and 45-minute reclaim for OC-match jobs.

`process_oc_match_job` is the BackgroundTasks entry and delegates to the
two-session worker (extract/match/excel/persist).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import NamedTuple, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.oc_match_job import OcMatchJob
from app.services.oc_match.mime import KIND_GEMINI, classify

logger = get_logger("services.oc_match.enqueue")

RECLAIM_AFTER = timedelta(minutes=45)
SKIP_MESSAGE = "MIME not eligible for Gemini OC-match"
STALE_MESSAGE = "Job marked error: running longer than 45 minutes"


class EnqueueResult(NamedTuple):
    job: OcMatchJob
    created: bool
    scheduled: bool


def process_oc_match_job(job_id: int) -> None:
    """Background entry: claim, extract, match, excel, persist."""
    from app.services.oc_match.worker import process_oc_match_job as _run

    _run(job_id)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _get_by_pair(db: Session, pedido_id: int, attachment_id: int) -> Optional[OcMatchJob]:
    return db.execute(
        select(OcMatchJob).where(
            OcMatchJob.pedido_id == pedido_id,
            OcMatchJob.attachment_id == attachment_id,
        )
    ).scalar_one_or_none()


def enqueue_oc_match(
    db: Session,
    *,
    pedido_id: int,
    attachment_id: int,
    filename: str,
    content: bytes,
    content_type: Optional[str] = None,
) -> EnqueueResult:
    """
    Persist one job per ``(pedido_id, attachment_id)``.

    Unique hit (any status) → reuse, never schedule a second task.
    Gemini MIME → ``queued`` + ``scheduled=True``.
    Office / unknown → ``skipped``, no Gemini.
    """
    existing = _get_by_pair(db, pedido_id, attachment_id)
    if existing is not None:
        return EnqueueResult(job=existing, created=False, scheduled=False)

    kind = classify(filename, content, content_type)
    now = _utcnow()
    if kind == KIND_GEMINI:
        status = OcMatchJob.STATUS_QUEUED
        error_message: Optional[str] = None
        finished_at: Optional[datetime] = None
        scheduled = True
    else:
        status = OcMatchJob.STATUS_SKIPPED
        error_message = SKIP_MESSAGE
        finished_at = now
        scheduled = False

    job = OcMatchJob(
        pedido_id=pedido_id,
        attachment_id=attachment_id,
        status=status,
        error_message=error_message,
        finished_at=finished_at,
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:
        winner = _get_by_pair(db, pedido_id, attachment_id)
        if winner is None:
            raise
        logger.info(
            "oc-match enqueue reuse after unique race pedido_id=%s attachment_id=%s job_id=%s",
            pedido_id,
            attachment_id,
            winner.id,
        )
        return EnqueueResult(job=winner, created=False, scheduled=False)

    return EnqueueResult(job=job, created=True, scheduled=scheduled)


def claim_queued_job(db: Session, job_id: int, *, now: Optional[datetime] = None) -> Optional[OcMatchJob]:
    """CAS ``queued → running``. Zero rows → no-op (None)."""
    stamp = now or _utcnow()
    result = db.execute(
        update(OcMatchJob)
        .where(
            OcMatchJob.id == job_id,
            OcMatchJob.status == OcMatchJob.STATUS_QUEUED,
        )
        .values(
            status=OcMatchJob.STATUS_RUNNING,
            started_at=stamp,
            updated_at=stamp,
        )
    )
    db.flush()
    if int(result.rowcount or 0) == 0:
        return None
    db.expire_all()
    return db.get(OcMatchJob, job_id)


def reclaim_stale_running(db: Session, *, now: Optional[datetime] = None) -> int:
    """Persist ``running`` longer than 45 minutes on ``started_at`` as retryable ``error``."""
    stamp = now or _utcnow()
    cutoff = stamp - RECLAIM_AFTER
    jobs = db.execute(select(OcMatchJob).where(OcMatchJob.status == OcMatchJob.STATUS_RUNNING)).scalars().all()
    marked = 0
    for job in jobs:
        started = job.started_at
        if started is not None and _as_utc(started) > cutoff:
            continue
        job.status = OcMatchJob.STATUS_ERROR
        job.error_message = STALE_MESSAGE
        job.progress_phase = None
        job.finished_at = stamp
        job.updated_at = stamp
        marked += 1
    if marked:
        db.flush()
    return marked


def delete_jobs_for_attachment(db: Session, attachment_id: int) -> int:
    """
    Drop OC-match jobs for an adjunto before the row is deleted.

    ``attachment_id`` is RESTRICT on ``compras_adjuntos``; callers that
    remove the adjunto must clear jobs (renglones cascade via ORM) first.
    """
    jobs = db.execute(select(OcMatchJob).where(OcMatchJob.attachment_id == attachment_id)).scalars().all()
    if not jobs:
        return 0
    for job in jobs:
        db.delete(job)
    db.flush()
    logger.info(
        "oc-match deleted %s job(s) for attachment_id=%s",
        len(jobs),
        attachment_id,
    )
    return len(jobs)


def queue_retry(db: Session, job: OcMatchJob, refrescar_doc_refs: bool = False) -> OcMatchJob:
    """Move a retryable ``error`` job back to ``queued``.

    Clears ``doc_refs_aplicado_at`` only when ``refrescar_doc_refs`` is True
    so the next persist can append_unique again.
    """
    if job.status != OcMatchJob.STATUS_ERROR:
        raise ValueError("job is not retryable")
    stamp = _utcnow()
    job.status = OcMatchJob.STATUS_QUEUED
    job.error_message = None
    job.progress_phase = None
    job.started_at = None
    job.finished_at = None
    job.updated_at = stamp
    if refrescar_doc_refs:
        job.doc_refs_aplicado_at = None
    db.flush()
    return job
