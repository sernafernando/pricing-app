"""Enqueue and drain PARA GANAR consultation jobs (refresh → P5).

Writers call `enqueue_consulta` (manual A1 / periodic P6). The ML worker
handler `para_ganar.consulta` claims one pending item at a time with fairness
across jobs (`last_progress_at`), refreshes catalog competition, then runs
`evaluar_mla`. Notify channel: `para_ganar_consulta`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.para_ganar_consulta_job import (
    ITEM_DONE,
    ITEM_FAILED,
    ITEM_PENDING,
    ITEM_PROCESSING,
    ITEM_SKIPPED,
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    SOURCE_MANUAL,
    SOURCES,
    ParaGanarConsultaJob,
    ParaGanarConsultaJobItem,
)
from app.models.para_ganar_revision_mla import REVISION_PENDIENTE, REVISION_SIN_NOVEDADES
from app.services.ml_catalog_competition_service import refrescar_competencia_catalogo
from app.services.para_ganar_evaluacion import evaluar_mla
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

CHANNEL = "para_ganar_consulta"
MAX_ATTEMPTS = 3
ERROR_MAX = 500
# Worker crash mid-MLA: release `processing` rows after this lease so fairness can retry.
PROCESSING_LEASE = timedelta(minutes=10)

_NOTIFY_SQL = text("SELECT pg_notify(:channel, '')")

_CLAIM_SQL = text(
    """
SELECT i.id
FROM para_ganar_consulta_job_item AS i
JOIN para_ganar_consulta_job AS j ON j.id = i.job_id
WHERE i.status = :item_pending
  AND j.status IN (:job_pending, :job_running)
  AND i.attempts < :max_attempts
ORDER BY j.last_progress_at NULLS FIRST, j.id, i.id
LIMIT 1
FOR UPDATE OF i SKIP LOCKED
"""
)


@dataclass(frozen=True)
class Claim:
    item_id: int
    job_id: int
    mla: str
    created_by_id: Optional[int]
    attempts: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def _clip_error(exc: BaseException | str) -> str:
    text_err = f"{type(exc).__name__}: {exc}" if isinstance(exc, BaseException) else str(exc)
    return text_err[:ERROR_MAX]


def notify_consulta(db: Session) -> None:
    """Wake the ML worker. No-op outside Postgres."""
    if not _postgres(db):
        return
    db.execute(_NOTIFY_SQL, {"channel": CHANNEL})


def enqueue_consulta(
    db: Session,
    mlas: list[str],
    *,
    created_by_id: Optional[int],
    source: str = SOURCE_MANUAL,
) -> ParaGanarConsultaJob:
    """Persist a job + pending items and notify the worker. Caller commits."""
    source_norm = (source or "").strip().lower()
    if source_norm not in SOURCES:
        raise ValueError(f"source inválido: {source!r}")

    seen: set[str] = set()
    unique: list[str] = []
    for raw in mlas:
        mla = (raw or "").strip().upper()
        if not mla or mla in seen:
            continue
        seen.add(mla)
        unique.append(mla)
    if not unique:
        raise ValueError("mlas vacío")

    job = ParaGanarConsultaJob(
        created_by_id=created_by_id,
        source=source_norm,
        status=JOB_PENDING,
        total_count=len(unique),
    )
    db.add(job)
    db.flush()
    for mla in unique:
        db.add(
            ParaGanarConsultaJobItem(
                job_id=job.id,
                mla=mla,
                status=ITEM_PENDING,
                attempts=0,
            )
        )
    db.flush()
    notify_consulta(db)
    return job


def reclaim_stale_processing(db: Session, *, now: Optional[datetime] = None) -> int:
    """Return stuck `processing` items to `pending` after PROCESSING_LEASE."""
    at = now or _utcnow()
    cutoff = at - PROCESSING_LEASE
    rows = (
        db.query(ParaGanarConsultaJobItem)
        .join(ParaGanarConsultaJob, ParaGanarConsultaJob.id == ParaGanarConsultaJobItem.job_id)
        .filter(
            ParaGanarConsultaJobItem.status == ITEM_PROCESSING,
            ParaGanarConsultaJob.status.in_((JOB_PENDING, JOB_RUNNING)),
            ParaGanarConsultaJob.last_progress_at.isnot(None),
            ParaGanarConsultaJob.last_progress_at < cutoff,
        )
        .all()
    )
    for item in rows:
        item.status = ITEM_PENDING
    if rows:
        db.flush()
    return len(rows)


def claim_one(db: Session) -> Optional[Claim]:
    """Lease the fairest pending item. Marks job running and charges one attempt."""
    now = _utcnow()
    item_id: Optional[int] = None
    if _postgres(db):
        row = db.execute(
            _CLAIM_SQL,
            {
                "item_pending": ITEM_PENDING,
                "job_pending": JOB_PENDING,
                "job_running": JOB_RUNNING,
                "max_attempts": MAX_ATTEMPTS,
            },
        ).first()
        if row is None:
            return None
        item_id = int(row[0])
    else:
        # Unit tests (SQLite): same fairness order without SKIP LOCKED.
        item = (
            db.query(ParaGanarConsultaJobItem)
            .join(ParaGanarConsultaJob, ParaGanarConsultaJob.id == ParaGanarConsultaJobItem.job_id)
            .filter(
                ParaGanarConsultaJobItem.status == ITEM_PENDING,
                ParaGanarConsultaJob.status.in_((JOB_PENDING, JOB_RUNNING)),
                ParaGanarConsultaJobItem.attempts < MAX_ATTEMPTS,
            )
            .order_by(
                ParaGanarConsultaJob.last_progress_at.asc().nullsfirst(),
                ParaGanarConsultaJob.id.asc(),
                ParaGanarConsultaJobItem.id.asc(),
            )
            .first()
        )
        if item is None:
            return None
        item_id = item.id

    item = db.get(ParaGanarConsultaJobItem, item_id)
    if item is None:
        return None
    job = db.get(ParaGanarConsultaJob, item.job_id)
    if job is None or job.status == JOB_CANCELLED:
        return None

    item.attempts = int(item.attempts or 0) + 1
    item.status = ITEM_PROCESSING
    if job.status == JOB_PENDING:
        job.status = JOB_RUNNING
        job.started_at = now
    job.last_progress_at = now
    db.flush()
    return Claim(
        item_id=item.id,
        job_id=job.id,
        mla=item.mla,
        created_by_id=job.created_by_id,
        attempts=item.attempts,
    )


def settle_success(
    db: Session,
    claim: Claim,
    *,
    item_status: str,
    revision_estado: Optional[str],
) -> None:
    """Mark item terminal and bump job counters. Completes the job when drained."""
    now = _utcnow()
    item = db.get(ParaGanarConsultaJobItem, claim.item_id)
    job = db.get(ParaGanarConsultaJob, claim.job_id)
    if item is None or job is None:
        return
    if item.status != ITEM_PROCESSING:
        return

    item.status = item_status
    item.revision_estado = revision_estado
    item.processed_at = now
    item.last_error = None
    if item_status == ITEM_DONE:
        job.done_count = int(job.done_count or 0) + 1
        if revision_estado == REVISION_PENDIENTE:
            job.pendiente_count = int(job.pendiente_count or 0) + 1
        elif revision_estado == REVISION_SIN_NOVEDADES:
            job.sin_novedades_count = int(job.sin_novedades_count or 0) + 1
    elif item_status == ITEM_SKIPPED:
        job.skipped_count = int(job.skipped_count or 0) + 1
    elif item_status == ITEM_FAILED:
        job.failed_count = int(job.failed_count or 0) + 1
    job.last_progress_at = now
    _maybe_finish_job(db, job, now)
    db.flush()


def settle_failure(db: Session, claim: Claim, error: str) -> None:
    """Retry later while attempts remain; otherwise mark item/job progress failed."""
    now = _utcnow()
    item = db.get(ParaGanarConsultaJobItem, claim.item_id)
    job = db.get(ParaGanarConsultaJob, claim.job_id)
    if item is None or job is None:
        return
    if item.status != ITEM_PROCESSING:
        return

    clipped = error[:ERROR_MAX]
    item.last_error = clipped
    job.last_error = clipped
    job.last_progress_at = now
    if claim.attempts >= MAX_ATTEMPTS:
        item.status = ITEM_FAILED
        item.processed_at = now
        job.failed_count = int(job.failed_count or 0) + 1
        _maybe_finish_job(db, job, now)
    else:
        # Release for another wake / fairness pass.
        item.status = ITEM_PENDING
    db.flush()


def _maybe_finish_job(db: Session, job: ParaGanarConsultaJob, now: datetime) -> None:
    if job.status == JOB_CANCELLED:
        return
    open_item = (
        db.query(ParaGanarConsultaJobItem.id)
        .filter(
            ParaGanarConsultaJobItem.job_id == job.id,
            ParaGanarConsultaJobItem.status.in_((ITEM_PENDING, ITEM_PROCESSING)),
        )
        .limit(1)
        .first()
    )
    if open_item is not None:
        return
    job.finished_at = now
    if int(job.failed_count or 0) > 0 and int(job.done_count or 0) == 0 and int(job.skipped_count or 0) == 0:
        job.status = JOB_FAILED
    else:
        job.status = JOB_COMPLETED


def process_claim(db: Session, claim: Claim) -> str:
    """Refresh one MLA then P5-evaluate. Returns settle kind: done|skipped|failed.

    `refrescar_competencia_catalogo` commits the session; caller must open a
    fresh session for settle. This helper expects a live session for refresh+eval
    and leaves settle to the drain (or settles in-process when using one session
    that survives the refresh commit — see `drain`).
    """
    rows = resolve_maybe_async(refrescar_competencia_catalogo(db, [claim.mla]))
    row = rows[0] if rows else None
    if row is None or getattr(row, "fetch_status", None) != "ok":
        detail = None
        if row is not None:
            detail = getattr(row, "error_detail", None) or getattr(row, "fetch_status", None)
        settle_success(
            db,
            claim,
            item_status=ITEM_SKIPPED,
            revision_estado=None,
        )
        if detail:
            item = db.get(ParaGanarConsultaJobItem, claim.item_id)
            if item is not None:
                item.last_error = str(detail)[:ERROR_MAX]
        return ITEM_SKIPPED

    estado = evaluar_mla(db, claim.mla, updated_by_id=claim.created_by_id)
    if estado is None:
        settle_success(db, claim, item_status=ITEM_SKIPPED, revision_estado=None)
        return ITEM_SKIPPED
    settle_success(db, claim, item_status=ITEM_DONE, revision_estado=estado)
    return ITEM_DONE


def drain(*, deadline: datetime) -> dict[str, int]:
    """Worker pass: claim → refresh+eval → settle until deadline or empty queue."""
    from app.core.database import get_background_db

    detail = {"claimed": 0, "done": 0, "skipped": 0, "failed": 0, "reclaimed": 0}
    with get_background_db() as db:
        detail["reclaimed"] = reclaim_stale_processing(db)

    while datetime.now(UTC) < deadline:
        claim: Optional[Claim] = None
        try:
            with get_background_db() as db:
                claim = claim_one(db)
                if claim is None:
                    break
                detail["claimed"] += 1
                # Refresh commits internally; keep claim fields and re-open after.
            with get_background_db() as db:
                outcome = process_claim(db, claim)
                if outcome == ITEM_DONE:
                    detail["done"] += 1
                elif outcome == ITEM_SKIPPED:
                    detail["skipped"] += 1
                else:
                    detail["failed"] += 1
        except Exception as exc:
            logger.exception("para_ganar.consulta: claim %s failed", claim)
            if claim is None:
                raise
            try:
                with get_background_db() as db:
                    settle_failure(db, claim, _clip_error(exc))
            except Exception:
                logger.exception("para_ganar.consulta: settle_failure also failed for %s", claim)
            detail["failed"] += 1
            # Continue with other jobs/items; fairness moves last_progress_at.
    return detail
