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
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.tn_reconcile_banlist import TnReconcileBanlist
from app.models.usuario import Usuario
from app.services.permisos_service import verificar_permiso
from app.services.tn_reconciliation_service import GBPFetchError, compute_verdicts, fetch_gbp_report_78

router = APIRouter(prefix="/tienda-nube-reconcile", tags=["tienda-nube-reconcile"])


class TnMatchResponse(BaseModel):
    product_id: int
    variant_id: int
    variant_sku: Optional[str]
    activo: bool
    published: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


class ReconcileRowResponse(BaseModel):
    ean: str
    verdict: str
    despublicar: bool
    gbp_row: dict
    tn_matches: List[TnMatchResponse]


class BanEanRequest(BaseModel):
    ean: str
    motivo: Optional[str] = None


class UnbanEanRequest(BaseModel):
    banlist_id: int


class BanlistEntryResponse(BaseModel):
    id: int
    ean: str
    motivo: Optional[str]
    usuario_nombre: str
    fecha_creacion: str

    model_config = ConfigDict(from_attributes=True)


@router.get("/reporte", response_model=List[ReconcileRowResponse])
async def get_reconciliation_report(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Live reconciliation report: GBP report 78 joined against TN on EAN.

    Nothing here is persisted — verdicts are recomputed on every call. Any
    GBP fetch failure surfaces a clear 502 to the operator with no partial
    write (Graceful Degradation requirement).
    """
    if not verificar_permiso(db, current_user, "admin.ver_tn_reconciliacion"):
        raise HTTPException(status_code=403, detail="No tienes permiso para ver la reconciliación de Tienda Nube")

    try:
        gbp_rows = await fetch_gbp_report_78()
    except GBPFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    tn_productos = db.query(TiendaNubeProducto).all()
    banned_eans = {row.ean for row in db.query(TnReconcileBanlist.ean).all()}

    verdicts = compute_verdicts(gbp_rows, tn_productos, banned_eans=banned_eans)

    return [
        ReconcileRowResponse(
            ean=v.ean,
            verdict=v.verdict,
            despublicar=v.despublicar,
            gbp_row=v.gbp_row,
            tn_matches=[TnMatchResponse.model_validate(tn) for tn in v.tn_matches],
        )
        for v in verdicts
    ]


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
    db.commit()
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
