"""Endpoints for TN Reconcile & Publish — Slice 1 (read-only reconciliation view).

Fetches GBP export report 78, joins it against `tienda_nube_productos` on
EAN, and returns a live-computed verdict per row (nothing is persisted except
the ban list). Mirrors `items_sin_mla.py`'s shape: explicit response models,
`Depends(get_current_user)`, permission gating via `verificar_permiso`.

Pool-safety note: this returns a one-shot in-memory JSON response (no
streaming), so `get_current_user` is the correct dependency here per the
design's open question — it does not hold the DB connection across an
awaited SOAP round-trip inside the request/response cycle in a way that
blocks the pool longer than any other synchronous endpoint.

Scaling note (review-driven): the internal `tienda_nube_productos` query is
bounded by `TN_PRODUCTOS_QUERY_CAP` as an explicit safety ceiling against
unbounded growth (this repo has a documented pool-exhaustion history), and
the `/reporte` response itself is paginated per the repo's `page`/`page_size`
convention. The Slice 1 report is a bounded internal admin view over a single
ERP export, so the frontend currently requests one generously-sized page; a
real pager UI is a fast-follow if the report ever exceeds that page size.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.tn_reconcile_banlist import TnReconcileBanlist
from app.models.usuario import Usuario
from app.services.permisos_service import verificar_permiso
from app.services.tn_reconciliation_service import GBPFetchError, compute_verdicts, fetch_gbp_report_78

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tienda-nube-reconcile", tags=["tienda-nube-reconcile"])

# Explicit ceiling on the internal TN catalog query — a full-table load with
# no bound is exactly the kind of unbounded-query pattern that has caused
# pool exhaustion in this repo before. If the table ever reaches this size,
# reconciliation may miss matches beyond the cap; this is a known Slice 1
# scaling limit, logged loudly rather than silently truncated.
TN_PRODUCTOS_QUERY_CAP = 50_000


class TnMatchResponse(BaseModel):
    product_id: int
    variant_id: int
    variant_sku: Optional[str]
    activo: Optional[bool] = None
    published: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


class ReconcileRowResponse(BaseModel):
    ean: str
    verdict: str
    despublicar: bool
    tn_matches: List[TnMatchResponse]


class ReconcileReportResponse(BaseModel):
    items: List[ReconcileRowResponse]
    total: int
    page: int
    page_size: int


class BanEanRequest(BaseModel):
    ean: str
    motivo: Optional[str] = None

    @field_validator("ean")
    @classmethod
    def _ean_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("El EAN no puede estar vacío")
        return stripped


class UnbanEanRequest(BaseModel):
    banlist_id: int


class BanlistEntryResponse(BaseModel):
    id: int
    ean: str
    motivo: Optional[str]
    usuario_nombre: str
    fecha_creacion: str

    model_config = ConfigDict(from_attributes=True)


@router.get("/reporte", response_model=ReconcileReportResponse)
async def get_reconciliation_report(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Live reconciliation report: GBP report 78 joined against TN on EAN.

    Nothing here is persisted — verdicts are recomputed on every call. Any
    GBP fetch failure surfaces a clear 502 to the operator with no partial
    write (Graceful Degradation requirement). The full verdict set is always
    computed (correctness requires the whole catalog for the EAN join and
    DUPLICADO detection); only the returned page of results is sliced.
    """
    if not verificar_permiso(db, current_user, "admin.ver_tn_reconciliacion"):
        raise HTTPException(status_code=403, detail="No tienes permiso para ver la reconciliación de Tienda Nube")

    try:
        gbp_rows = await fetch_gbp_report_78()
    except GBPFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    tn_productos = db.query(TiendaNubeProducto).limit(TN_PRODUCTOS_QUERY_CAP).all()
    if len(tn_productos) >= TN_PRODUCTOS_QUERY_CAP:
        logger.warning(
            "tienda_nube_productos row count reached TN_PRODUCTOS_QUERY_CAP=%d — "
            "reconciliation may be missing matches beyond the cap",
            TN_PRODUCTOS_QUERY_CAP,
        )
    banned_eans = {row.ean for row in db.query(TnReconcileBanlist.ean).all()}

    verdicts = compute_verdicts(gbp_rows, tn_productos, banned_eans=banned_eans)

    total = len(verdicts)
    start = (page - 1) * page_size
    page_verdicts = verdicts[start : start + page_size]

    items = [
        ReconcileRowResponse(
            ean=v.ean,
            verdict=v.verdict,
            despublicar=v.despublicar,
            tn_matches=[TnMatchResponse.model_validate(tn) for tn in v.tn_matches],
        )
        for v in page_verdicts
    ]

    return ReconcileReportResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/baneados", response_model=List[BanlistEntryResponse])
def get_banlist(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_reconcile_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de reconciliación TN")

    baneados = (
        db.query(TnReconcileBanlist, Usuario)
        .join(Usuario, Usuario.id == TnReconcileBanlist.usuario_id)
        .order_by(TnReconcileBanlist.fecha_creacion.desc())
        .all()
    )

    return [
        BanlistEntryResponse(
            id=entry.id,
            ean=entry.ean,
            motivo=entry.motivo,
            usuario_nombre=usuario.nombre,
            fecha_creacion=entry.fecha_creacion.isoformat(),
        )
        for entry, usuario in baneados
    ]


@router.post("/banear")
def banear_ean(
    request: BanEanRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_reconcile_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de reconciliación TN")

    existente = db.query(TnReconcileBanlist).filter(TnReconcileBanlist.ean == request.ean).first()
    if existente:
        raise HTTPException(status_code=400, detail="El EAN ya está en la banlist")

    nuevo_ban = TnReconcileBanlist(ean=request.ean, motivo=request.motivo, usuario_id=current_user.id)
    db.add(nuevo_ban)
    try:
        db.commit()
    except IntegrityError:
        # TOCTOU guard: a concurrent request may have inserted the same EAN
        # between the existence check above and this commit. The unique
        # index is the real guarantee — this just turns the resulting
        # constraint violation into the intended 400 instead of a 500.
        db.rollback()
        raise HTTPException(status_code=400, detail="El EAN ya está en la banlist") from None
    db.refresh(nuevo_ban)

    return {"success": True, "message": f"EAN {request.ean} agregado a la banlist", "banlist_id": nuevo_ban.id}


@router.post("/desbanear")
def desbanear_ean(
    request: UnbanEanRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    if not verificar_permiso(db, current_user, "admin.gestionar_tn_reconcile_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de reconciliación TN")

    ban_entry = db.query(TnReconcileBanlist).filter(TnReconcileBanlist.id == request.banlist_id).first()
    if not ban_entry:
        raise HTTPException(status_code=404, detail="Entrada de banlist no encontrada")

    ean = ban_entry.ean
    db.delete(ban_entry)
    db.commit()

    return {"success": True, "message": f"EAN {ean} removido de la banlist"}
