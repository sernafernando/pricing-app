"""
CRUD de transportes interprovinciales para envíos flex.

Cada transporte representa un intermediario que recibe paquetes de la logística
y los entrega al cliente final en otra provincia.
Ej: Cruz del Sur, Vía Cargo, Chevallier Cargas.

Flujo: Depósito → [Logística] → [Transporte] → [Cliente]
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.transporte import Transporte
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────


class TransporteResponse(BaseModel):
    """Transporte interprovincial para asignar a envíos."""

    id: int
    nombre: str
    cuit: Optional[str] = None
    direccion: Optional[str] = None
    telefono: Optional[str] = None
    horario: Optional[str] = None
    activa: bool
    color: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TransporteCreate(BaseModel):
    """Payload para crear transporte."""

    nombre: str = Field(min_length=1, max_length=150)
    cuit: Optional[str] = Field(
        None,
        max_length=13,
        description="CUIT del transporte, ej: 30-12345678-9",
    )
    direccion: Optional[str] = Field(
        None,
        max_length=500,
        description="Dirección de la terminal/depósito del transporte",
    )
    telefono: Optional[str] = Field(None, max_length=50)
    horario: Optional[str] = Field(
        None,
        max_length=200,
        description="Horario de recepción, ej: Lun-Vie 8:00-17:00",
    )
    color: Optional[str] = Field(
        None,
        max_length=7,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Color hex para badge, ej: #3b82f6",
    )


class TransporteUpdate(BaseModel):
    """Payload para actualizar transporte."""

    nombre: Optional[str] = Field(None, min_length=1, max_length=150)
    cuit: Optional[str] = Field(None, max_length=13)
    direccion: Optional[str] = Field(None, max_length=500)
    telefono: Optional[str] = Field(None, max_length=50)
    horario: Optional[str] = Field(None, max_length=200)
    color: Optional[str] = Field(
        None,
        max_length=7,
        description="Color hex para badge. Enviar string vacío para borrar.",
    )
    activa: Optional[bool] = None


# ── Endpoints ────────────────────────────────────────────────────────


@router.get(
    "/transportes",
    response_model=List[TransporteResponse],
    summary="Listar transportes",
)
def listar_transportes(
    incluir_inactivas: bool = Query(False, description="Incluir transportes desactivados"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[TransporteResponse]:
    """
    Devuelve los transportes disponibles.
    Por defecto solo los activos; con ?incluir_inactivas=true trae todos.
    """
    query = db.query(Transporte)

    if not incluir_inactivas:
        query = query.filter(Transporte.activa.is_(True))

    query = query.order_by(Transporte.nombre)
    return query.all()


@router.post(
    "/transportes",
    response_model=TransporteResponse,
    status_code=201,
    summary="Crear transporte",
)
def crear_transporte(
    payload: TransporteCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TransporteResponse:
    """Crea un nuevo transporte. El nombre debe ser único."""

    existente = db.query(Transporte).filter(Transporte.nombre == payload.nombre).first()
    if existente:
        raise HTTPException(400, f"Ya existe un transporte con el nombre '{payload.nombre}'")

    transporte = Transporte(
        nombre=payload.nombre,
        cuit=payload.cuit,
        direccion=payload.direccion,
        telefono=payload.telefono,
        horario=payload.horario,
        color=payload.color,
    )
    db.add(transporte)
    db.commit()
    db.refresh(transporte)

    return transporte


@router.put(
    "/transportes/{transporte_id}",
    response_model=TransporteResponse,
    summary="Actualizar transporte",
)
def actualizar_transporte(
    transporte_id: int,
    payload: TransporteUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TransporteResponse:
    """Actualiza datos de un transporte."""

    transporte = db.query(Transporte).filter(Transporte.id == transporte_id).first()
    if not transporte:
        raise HTTPException(404, "Transporte no encontrado")

    if payload.nombre is not None:
        existente = (
            db.query(Transporte).filter(Transporte.nombre == payload.nombre, Transporte.id != transporte_id).first()
        )
        if existente:
            raise HTTPException(400, f"Ya existe un transporte con el nombre '{payload.nombre}'")
        transporte.nombre = payload.nombre

    if payload.cuit is not None:
        transporte.cuit = payload.cuit if payload.cuit else None

    if payload.direccion is not None:
        transporte.direccion = payload.direccion if payload.direccion else None

    if payload.telefono is not None:
        transporte.telefono = payload.telefono if payload.telefono else None

    if payload.horario is not None:
        transporte.horario = payload.horario if payload.horario else None

    if payload.color is not None:
        transporte.color = payload.color if payload.color else None

    if payload.activa is not None:
        transporte.activa = payload.activa

    db.commit()
    db.refresh(transporte)

    return transporte


@router.delete(
    "/transportes/{transporte_id}",
    response_model=TransporteResponse,
    summary="Desactivar transporte (soft delete)",
)
def desactivar_transporte(
    transporte_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TransporteResponse:
    """Soft delete: marca el transporte como inactivo."""

    transporte = db.query(Transporte).filter(Transporte.id == transporte_id).first()
    if not transporte:
        raise HTTPException(404, "Transporte no encontrado")

    transporte.activa = False
    db.commit()
    db.refresh(transporte)

    return transporte
