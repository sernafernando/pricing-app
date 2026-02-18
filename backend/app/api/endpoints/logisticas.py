"""
CRUD de logísticas para envíos flex.

Cada logística representa un operador de entrega (ej: Andreani, OCA, Flex propio).
Se asignan a etiquetas de envío para organizar la distribución diaria.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.logistica import Logistica

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────


class LogisticaResponse(BaseModel):
    """Logística para asignar a envíos."""

    id: int
    nombre: str
    activa: bool
    color: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class LogisticaCreate(BaseModel):
    """Payload para crear logística."""

    nombre: str = Field(min_length=1, max_length=100)
    color: Optional[str] = Field(
        None,
        max_length=7,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Color hex para badge, ej: #3b82f6",
    )


class LogisticaUpdate(BaseModel):
    """Payload para actualizar logística."""

    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = Field(
        None,
        max_length=7,
        description="Color hex para badge, ej: #3b82f6. Enviar string vacío para borrar.",
    )
    activa: Optional[bool] = None


# ── Endpoints ────────────────────────────────────────────────────────


@router.get(
    "/logisticas",
    response_model=List[LogisticaResponse],
    summary="Listar logísticas",
)
def listar_logisticas(
    incluir_inactivas: bool = Query(False, description="Incluir logísticas desactivadas"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[LogisticaResponse]:
    """
    Devuelve las logísticas disponibles.
    Por defecto solo las activas; con ?incluir_inactivas=true trae todas.
    """
    query = db.query(Logistica)

    if not incluir_inactivas:
        query = query.filter(Logistica.activa.is_(True))

    query = query.order_by(Logistica.nombre)
    return query.all()


@router.post(
    "/logisticas",
    response_model=LogisticaResponse,
    status_code=201,
    summary="Crear logística",
)
def crear_logistica(
    payload: LogisticaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> LogisticaResponse:
    """Crea una nueva logística. El nombre debe ser único."""

    existente = db.query(Logistica).filter(Logistica.nombre == payload.nombre).first()
    if existente:
        raise HTTPException(400, f"Ya existe una logística con el nombre '{payload.nombre}'")

    logistica = Logistica(
        nombre=payload.nombre,
        color=payload.color,
    )
    db.add(logistica)
    db.commit()
    db.refresh(logistica)

    return logistica


@router.put(
    "/logisticas/{logistica_id}",
    response_model=LogisticaResponse,
    summary="Actualizar logística",
)
def actualizar_logistica(
    logistica_id: int,
    payload: LogisticaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> LogisticaResponse:
    """Actualiza nombre, color o estado activo de una logística."""

    logistica = db.query(Logistica).filter(Logistica.id == logistica_id).first()
    if not logistica:
        raise HTTPException(404, "Logística no encontrada")

    if payload.nombre is not None:
        # Verificar unicidad
        existente = db.query(Logistica).filter(Logistica.nombre == payload.nombre, Logistica.id != logistica_id).first()
        if existente:
            raise HTTPException(400, f"Ya existe una logística con el nombre '{payload.nombre}'")
        logistica.nombre = payload.nombre

    if payload.color is not None:
        logistica.color = payload.color if payload.color else None

    if payload.activa is not None:
        logistica.activa = payload.activa

    db.commit()
    db.refresh(logistica)

    return logistica


@router.delete(
    "/logisticas/{logistica_id}",
    response_model=LogisticaResponse,
    summary="Desactivar logística (soft delete)",
)
def desactivar_logistica(
    logistica_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> LogisticaResponse:
    """Soft delete: marca la logística como inactiva."""

    logistica = db.query(Logistica).filter(Logistica.id == logistica_id).first()
    if not logistica:
        raise HTTPException(404, "Logística no encontrada")

    logistica.activa = False
    db.commit()
    db.refresh(logistica)

    return logistica
