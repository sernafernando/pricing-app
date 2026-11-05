"""Router: read-only view of the publication repair job (envio / sku).

No ML calls and no writes: it only reads `publicacion_repair_run`, `publicacion_repair_event` and the
repair rows of `ml_write_log`. Events are enriched live with `ml_items.title` and
`productos_erp.descripcion` for the control UI. Permission gate: `ml_ops.ver` (`require_permiso`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.models.ml_publications import MlItem
from app.models.ml_write_log import (
    ACTION_ENABLE_FLEX,
    ACTION_UPDATE_DATA,
    ACTION_UPDATE_SHIPPING,
    MlWriteLog,
)
from app.models.producto import ProductoERP
from app.models.publicacion_repair import (
    PublicacionRepairEvent,
    PublicacionRepairRun,
)
from app.models.usuario import Usuario

PERMISO_VER = "ml_ops.ver"

REPAIR_ML_WRITE_ACTIONS = (ACTION_UPDATE_SHIPPING, ACTION_ENABLE_FLEX, ACTION_UPDATE_DATA)

router = APIRouter(prefix="/ml-publications", tags=["ML Publications Repair"])


def get_repair_db(db: Session = Depends(get_db)) -> Session:
    return db


# ── Schemas ──────────────────────────────────────────────────────


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    status: str
    trigger: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    scanned: int
    changed: int
    skipped: int
    errors: int
    error_message: Optional[str] = None


class RunListOut(BaseModel):
    items: list[RunOut]
    total: int
    page: int
    page_size: int


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    mla_id: str
    item_id: Optional[int] = None
    action: str
    before: Optional[Any] = None
    after: Optional[Any] = None
    detail: Optional[str] = None
    created_at: datetime
    # Live join for the control view (not stored on the event row).
    title: Optional[str] = None
    descripcion: Optional[str] = None
    # Only populated on the cross-run MLA endpoint.
    run_job_type: Optional[str] = None
    run_started_at: Optional[datetime] = None


class BreakdownOut(BaseModel):
    action: str
    detail: Optional[str] = None
    count: int


class RunDetailOut(BaseModel):
    run: RunOut
    events: list[EventOut]
    total: int
    page: int
    page_size: int
    breakdown: list[BreakdownOut]


class MlWriteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    payload: Optional[Any] = None
    created_at: datetime


class MlaEventsOut(BaseModel):
    mla_id: str
    events: list[EventOut]
    total: int
    page: int
    page_size: int
    ml_writes: list[MlWriteOut]


# ── Helpers ──────────────────────────────────────────────────────


_AR_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def _live_labels(
    db: Session, events: list[PublicacionRepairEvent]
) -> tuple[dict[str, Optional[str]], dict[int, Optional[str]]]:
    """Batch-load current ml_items.title and productos_erp.descripcion for a page of events."""
    mlas = sorted({e.mla_id for e in events if e.mla_id})
    item_ids = sorted({e.item_id for e in events if e.item_id is not None})
    titles: dict[str, Optional[str]] = {}
    descripciones: dict[int, Optional[str]] = {}
    if mlas:
        for item_id, title in db.query(MlItem.item_id, MlItem.title).filter(MlItem.item_id.in_(mlas)).all():
            titles[str(item_id)] = title
    if item_ids:
        for item_id, descripcion in (
            db.query(ProductoERP.item_id, ProductoERP.descripcion).filter(ProductoERP.item_id.in_(item_ids)).all()
        ):
            descripciones[int(item_id)] = descripcion
    return titles, descripciones


def _event_out(
    ev: PublicacionRepairEvent,
    *,
    titles: dict[str, Optional[str]],
    descripciones: dict[int, Optional[str]],
    run_job_type: Optional[str] = None,
    run_started_at: Optional[datetime] = None,
) -> EventOut:
    eo = EventOut.model_validate(ev)
    eo.title = titles.get(ev.mla_id)
    eo.descripcion = descripciones.get(ev.item_id) if ev.item_id is not None else None
    eo.run_job_type = run_job_type
    eo.run_started_at = run_started_at
    return eo


def _parse_dt(value: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    # Accept date-only or full ISO; normalize to tz-aware. A date-only value is
    # interpreted in Argentina's zone, since that is what the date picker means.
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"fecha inválida: {value}"
        ) from exc
    date_only = "T" not in text and " " not in text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_AR_TZ if date_only else timezone.utc)
    # A date-only `hasta` covers the whole day, not just its midnight.
    if end_of_day and date_only:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/repair/runs", response_model=RunListOut)
def list_runs(
    job_type: Optional[str] = Query(default=None),
    run_status: Optional[str] = Query(default=None, alias="status"),
    desde: Optional[str] = Query(default=None),
    hasta: Optional[str] = Query(default=None),
    page: int = Query(1, ge=1, le=1_000_000),
    page_size: int = Query(50, ge=1, le=200),
    _user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_repair_db),
) -> RunListOut:
    desde_dt = _parse_dt(desde)
    hasta_dt = _parse_dt(hasta, end_of_day=True)

    q = db.query(PublicacionRepairRun)
    if job_type:
        q = q.filter(PublicacionRepairRun.job_type == job_type)
    if run_status:
        q = q.filter(PublicacionRepairRun.status == run_status)
    if desde_dt is not None:
        q = q.filter(PublicacionRepairRun.started_at >= desde_dt)
    if hasta_dt is not None:
        q = q.filter(PublicacionRepairRun.started_at <= hasta_dt)

    total = q.count()
    rows = (
        q.order_by(PublicacionRepairRun.started_at.desc(), PublicacionRepairRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return RunListOut(items=[RunOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/repair/runs/{run_id}", response_model=RunDetailOut)
def get_run(
    run_id: int,
    action: Optional[str] = Query(default=None),
    detail: Optional[str] = Query(default=None),
    page: int = Query(1, ge=1, le=1_000_000),
    page_size: int = Query(50, ge=1, le=200),
    _user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_repair_db),
) -> RunDetailOut:
    run = db.get(PublicacionRepairRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run no encontrado")

    eq = db.query(PublicacionRepairEvent).filter(PublicacionRepairEvent.run_id == run_id)
    if action:
        eq = eq.filter(PublicacionRepairEvent.action == action)
    if detail is not None:
        if detail == "":
            eq = eq.filter(PublicacionRepairEvent.detail.is_(None))
        else:
            eq = eq.filter(PublicacionRepairEvent.detail == detail)

    total = eq.count()
    events = (
        eq.order_by(PublicacionRepairEvent.created_at.desc(), PublicacionRepairEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # Breakdown over ALL events of the run (ignoring action/detail filters).
    breakdown_rows = (
        db.query(
            PublicacionRepairEvent.action,
            PublicacionRepairEvent.detail,
            func.count().label("c"),
        )
        .filter(PublicacionRepairEvent.run_id == run_id)
        .group_by(PublicacionRepairEvent.action, PublicacionRepairEvent.detail)
        .order_by(func.count().desc())
        .all()
    )
    breakdown = [BreakdownOut(action=r[0], detail=r[1], count=int(r[2])) for r in breakdown_rows]

    titles, descripciones = _live_labels(db, events)
    return RunDetailOut(
        run=RunOut.model_validate(run),
        events=[_event_out(e, titles=titles, descripciones=descripciones) for e in events],
        total=total,
        page=page,
        page_size=page_size,
        breakdown=breakdown,
    )


@router.get("/repair/events", response_model=MlaEventsOut)
def events_by_mla(
    mla_id: str = Query(..., min_length=1),
    page: int = Query(1, ge=1, le=1_000_000),
    page_size: int = Query(50, ge=1, le=200),
    _user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_repair_db),
) -> MlaEventsOut:
    # Events across runs for this MLA, newest first, with run context.
    q = (
        db.query(PublicacionRepairEvent, PublicacionRepairRun)
        .join(PublicacionRepairRun, PublicacionRepairRun.id == PublicacionRepairEvent.run_id)
        .filter(PublicacionRepairEvent.mla_id == mla_id)
    )
    total = q.count()
    pairs = (
        q.order_by(PublicacionRepairEvent.created_at.desc(), PublicacionRepairEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    event_rows = [ev for ev, _run in pairs]
    titles, descripciones = _live_labels(db, event_rows)
    events: list[EventOut] = [
        _event_out(
            ev,
            titles=titles,
            descripciones=descripciones,
            run_job_type=run.job_type,
            run_started_at=run.started_at,
        )
        for ev, run in pairs
    ]

    # Repair rows in ml_write_log for this MLA.
    writes = (
        db.query(MlWriteLog)
        .filter(
            MlWriteLog.mla == mla_id,
            MlWriteLog.resource == "item",
            MlWriteLog.action.in_(REPAIR_ML_WRITE_ACTIONS),
            MlWriteLog.usuario_id.is_(None),
        )
        .order_by(MlWriteLog.created_at.desc(), MlWriteLog.id.desc())
        .limit(200)
        .all()
    )
    ml_writes = [MlWriteOut.model_validate(w) for w in writes]

    return MlaEventsOut(mla_id=mla_id, events=events, total=total, page=page, page_size=page_size, ml_writes=ml_writes)
