"""
Endpoints para gestión de colectas.

Una colecta agrupa N etiquetas (paquetes) que salen juntas en un mismo retiro.
Identificada por (fecha, numero). Estados: pendiente | despachada.
"""

import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.colecta import Colecta
from app.models.etiqueta_colecta import EtiquetaColecta
from app.services.permisos_service import verificar_permiso
from app.core.sse import sse_publish_bg

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic models ──────────────────────────────────────────────


class ColectaResponse(BaseModel):
    """Colecta con conteo de etiquetas."""

    id: int
    fecha: date
    numero: int
    estado: str
    despachada_at: Optional[datetime] = None
    observaciones: Optional[str] = None
    total_etiquetas: int = 0

    model_config = ConfigDict(from_attributes=True)


class ColectaCreateRequest(BaseModel):
    """Crea una colecta. Si numero es None, auto-asigna el siguiente disponible."""

    fecha: date
    numero: Optional[int] = Field(None, ge=1, description="Si se omite, se autoasigna")
    observaciones: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ColectaDespachadaRequest(BaseModel):
    """Marca una colecta como despachada."""

    observaciones: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ── Helpers ──────────────────────────────────────────────────────


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    if not verificar_permiso(db, user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


def _siguiente_numero(db: Session, fecha: date) -> int:
    """Retorna el siguiente número de colecta disponible para una fecha."""
    max_num = db.query(func.max(Colecta.numero)).filter(Colecta.fecha == fecha).scalar()
    return (max_num or 0) + 1


def _serializar_con_total(db: Session, colectas: List[Colecta]) -> List[ColectaResponse]:
    """Serializa colectas con total_etiquetas en una sola query."""
    if not colectas:
        return []

    ids = [c.id for c in colectas]
    counts = dict(
        db.query(EtiquetaColecta.colecta_id, func.count(EtiquetaColecta.id))
        .filter(EtiquetaColecta.colecta_id.in_(ids))
        .group_by(EtiquetaColecta.colecta_id)
        .all()
    )

    return [
        ColectaResponse(
            id=c.id,
            fecha=c.fecha,
            numero=c.numero,
            estado=c.estado,
            despachada_at=c.despachada_at,
            observaciones=c.observaciones,
            total_etiquetas=counts.get(c.id, 0),
        )
        for c in colectas
    ]


# ── Endpoints ────────────────────────────────────────────────────


@router.get(
    "/colectas",
    response_model=List[ColectaResponse],
    summary="Listar colectas",
)
def listar_colectas(
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    estado: Optional[str] = Query(None, description="pendiente | despachada"),
    incluir_despachadas: bool = Query(True, description="Si False, oculta las despachadas"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[ColectaResponse]:
    """Lista colectas con filtros y conteo de etiquetas vinculadas."""
    _check_permiso(db, current_user, "envios_flex.ver")

    q = db.query(Colecta)

    if fecha_desde:
        q = q.filter(Colecta.fecha >= fecha_desde)
    if fecha_hasta:
        q = q.filter(Colecta.fecha <= fecha_hasta)
    if estado:
        q = q.filter(Colecta.estado == estado)
    elif not incluir_despachadas:
        q = q.filter(Colecta.estado == Colecta.ESTADO_PENDIENTE)

    colectas = q.order_by(Colecta.fecha.desc(), Colecta.numero.asc()).all()
    return _serializar_con_total(db, colectas)


@router.get(
    "/colectas/siguiente-numero",
    response_model=dict,
    summary="Siguiente número de colecta para una fecha",
)
def siguiente_numero_colecta(
    fecha: date = Query(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Devuelve el siguiente número disponible para una fecha dada."""
    _check_permiso(db, current_user, "envios_flex.ver")
    return {"fecha": fecha.isoformat(), "siguiente": _siguiente_numero(db, fecha)}


@router.post(
    "/colectas",
    response_model=ColectaResponse,
    summary="Crear colecta",
)
def crear_colecta(
    payload: ColectaCreateRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ColectaResponse:
    """
    Crea una colecta nueva. Si numero es None, auto-asigna el siguiente disponible
    para la fecha dada.
    """
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    numero = payload.numero or _siguiente_numero(db, payload.fecha)

    existente = db.query(Colecta).filter(and_(Colecta.fecha == payload.fecha, Colecta.numero == numero)).first()
    if existente:
        raise HTTPException(409, f"Ya existe colecta {payload.fecha} #{numero}")

    colecta = Colecta(
        fecha=payload.fecha,
        numero=numero,
        estado=Colecta.ESTADO_PENDIENTE,
        observaciones=payload.observaciones,
    )
    db.add(colecta)
    db.commit()
    db.refresh(colecta)

    sse_publish_bg("colectas:changed", {"hint": "reload"})

    return ColectaResponse(
        id=colecta.id,
        fecha=colecta.fecha,
        numero=colecta.numero,
        estado=colecta.estado,
        despachada_at=colecta.despachada_at,
        observaciones=colecta.observaciones,
        total_etiquetas=0,
    )


@router.patch(
    "/colectas/{colecta_id}/despachar",
    response_model=ColectaResponse,
    summary="Marcar colecta como despachada",
)
def despachar_colecta(
    colecta_id: int,
    payload: ColectaDespachadaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ColectaResponse:
    """Marca una colecta como despachada (ya se fue)."""
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    colecta = db.query(Colecta).filter(Colecta.id == colecta_id).first()
    if not colecta:
        raise HTTPException(404, "Colecta no encontrada")

    if colecta.estado == Colecta.ESTADO_DESPACHADA:
        raise HTTPException(400, "La colecta ya está despachada")

    colecta.estado = Colecta.ESTADO_DESPACHADA
    colecta.despachada_at = datetime.utcnow()
    if payload.observaciones is not None:
        colecta.observaciones = payload.observaciones

    db.commit()
    db.refresh(colecta)

    sse_publish_bg("colectas:changed", {"hint": "reload"})

    total = (db.query(func.count(EtiquetaColecta.id)).filter(EtiquetaColecta.colecta_id == colecta.id).scalar()) or 0

    return ColectaResponse(
        id=colecta.id,
        fecha=colecta.fecha,
        numero=colecta.numero,
        estado=colecta.estado,
        despachada_at=colecta.despachada_at,
        observaciones=colecta.observaciones,
        total_etiquetas=total,
    )


@router.patch(
    "/colectas/{colecta_id}/reabrir",
    response_model=ColectaResponse,
    summary="Reabrir colecta despachada",
)
def reabrir_colecta(
    colecta_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ColectaResponse:
    """Vuelve una colecta despachada al estado pendiente (por si se despachó por error)."""
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    colecta = db.query(Colecta).filter(Colecta.id == colecta_id).first()
    if not colecta:
        raise HTTPException(404, "Colecta no encontrada")

    if colecta.estado == Colecta.ESTADO_PENDIENTE:
        raise HTTPException(400, "La colecta ya está pendiente")

    colecta.estado = Colecta.ESTADO_PENDIENTE
    colecta.despachada_at = None

    db.commit()
    db.refresh(colecta)

    sse_publish_bg("colectas:changed", {"hint": "reload"})

    total = (db.query(func.count(EtiquetaColecta.id)).filter(EtiquetaColecta.colecta_id == colecta.id).scalar()) or 0

    return ColectaResponse(
        id=colecta.id,
        fecha=colecta.fecha,
        numero=colecta.numero,
        estado=colecta.estado,
        despachada_at=colecta.despachada_at,
        observaciones=colecta.observaciones,
        total_etiquetas=total,
    )


@router.delete(
    "/colectas/{colecta_id}",
    response_model=dict,
    summary="Borrar colecta",
)
def borrar_colecta(
    colecta_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Borra una colecta. Solo se permite si NO tiene etiquetas asociadas (para evitar
    pérdida accidental). Si querés borrar con etiquetas, primero borralas.
    """
    _check_permiso(db, current_user, "envios_flex.eliminar")

    colecta = db.query(Colecta).filter(Colecta.id == colecta_id).first()
    if not colecta:
        raise HTTPException(404, "Colecta no encontrada")

    total = (db.query(func.count(EtiquetaColecta.id)).filter(EtiquetaColecta.colecta_id == colecta_id).scalar()) or 0

    if total > 0:
        raise HTTPException(
            400,
            f"La colecta tiene {total} etiqueta(s). Borralas primero.",
        )

    db.delete(colecta)
    db.commit()

    sse_publish_bg("colectas:changed", {"hint": "reload"})

    return {"ok": True, "id": colecta_id}
