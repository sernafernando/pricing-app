"""
Router del módulo RRHH - Sanciones disciplinarias.

Endpoints:
- CRUD de sanciones (crear, listar, detalle, anular)
- CRUD de tipos de sanción (configuración)
"""

from datetime import date, datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_sancion import RRHHSancion, RRHHTipoSancion
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/rrhh", tags=["rrhh-sanciones"])


# ──────────────────────────────────────────────
# SCHEMAS
# ──────────────────────────────────────────────


class TipoSancionCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: Optional[str] = Field(default=None, max_length=500)
    dias_suspension: Optional[int] = None
    requiere_descuento: bool = False
    orden: int = 0


class TipoSancionUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=100)
    descripcion: Optional[str] = Field(default=None, max_length=500)
    dias_suspension: Optional[int] = None
    requiere_descuento: Optional[bool] = None
    activo: Optional[bool] = None
    orden: Optional[int] = None


class TipoSancionResponse(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str] = None
    dias_suspension: Optional[int] = None
    requiere_descuento: bool
    activo: bool
    orden: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SancionCreate(BaseModel):
    empleado_id: int
    tipo_sancion_id: int
    fecha: date
    motivo: str = Field(min_length=1)
    descripcion: Optional[str] = None
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None


class SancionAnularRequest(BaseModel):
    motivo: str = Field(min_length=1)


class SancionResponse(BaseModel):
    id: int
    empleado_id: int
    tipo_sancion_id: int
    fecha: date
    motivo: str
    descripcion: Optional[str] = None
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    anulada: bool
    anulada_motivo: Optional[str] = None
    anulada_por_id: Optional[int] = None
    anulada_at: Optional[datetime] = None
    aplicada_por_id: int
    created_at: Optional[datetime] = None
    # Joined
    tipo_sancion_nombre: Optional[str] = None
    empleado_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SancionListResponse(BaseModel):
    items: list[SancionResponse]
    total: int
    page: int
    page_size: int


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────


def _sancion_to_response(s: RRHHSancion) -> SancionResponse:
    """Convert SQLAlchemy model to response, enriching with joined data."""
    data = SancionResponse.model_validate(s)
    if s.tipo_sancion:
        data.tipo_sancion_nombre = s.tipo_sancion.nombre
    if s.empleado:
        data.empleado_nombre = s.empleado.nombre_completo
    return data


# ──────────────────────────────────────────────
# ENDPOINTS — Tipos de Sanción
# ──────────────────────────────────────────────


@router.get("/tipos-sancion", response_model=list[TipoSancionResponse])
def list_tipos_sancion(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TipoSancionResponse]:
    """Listar tipos de sanción (activos e inactivos)."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    tipos = db.query(RRHHTipoSancion).order_by(RRHHTipoSancion.orden, RRHHTipoSancion.nombre).all()
    return [TipoSancionResponse.model_validate(t) for t in tipos]


@router.post(
    "/tipos-sancion",
    response_model=TipoSancionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_tipo_sancion(
    body: TipoSancionCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TipoSancionResponse:
    """Crear tipo de sanción."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.config"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.config")

    existing = db.query(RRHHTipoSancion).filter(RRHHTipoSancion.nombre == body.nombre).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un tipo con ese nombre")

    tipo = RRHHTipoSancion(**body.model_dump())
    db.add(tipo)
    db.commit()
    db.refresh(tipo)
    return TipoSancionResponse.model_validate(tipo)


@router.put("/tipos-sancion/{tipo_id}", response_model=TipoSancionResponse)
def update_tipo_sancion(
    tipo_id: int,
    body: TipoSancionUpdate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TipoSancionResponse:
    """Actualizar tipo de sanción."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.config"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.config")

    tipo = db.query(RRHHTipoSancion).filter(RRHHTipoSancion.id == tipo_id).first()
    if not tipo:
        raise HTTPException(status_code=404, detail="Tipo de sanción no encontrado")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tipo, field, value)

    db.commit()
    db.refresh(tipo)
    return TipoSancionResponse.model_validate(tipo)


# ──────────────────────────────────────────────
# ENDPOINTS — Sanciones
# ──────────────────────────────────────────────


@router.get("/sanciones", response_model=SancionListResponse)
def list_sanciones(
    empleado_id: Optional[int] = Query(default=None),
    tipo_sancion_id: Optional[int] = Query(default=None),
    fecha_desde: Optional[date] = Query(default=None),
    fecha_hasta: Optional[date] = Query(default=None),
    incluir_anuladas: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SancionListResponse:
    """Listar sanciones con filtros opcionales."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    query = db.query(RRHHSancion).options(
        joinedload(RRHHSancion.tipo_sancion),
        joinedload(RRHHSancion.empleado),
    )

    if empleado_id:
        query = query.filter(RRHHSancion.empleado_id == empleado_id)
    if tipo_sancion_id:
        query = query.filter(RRHHSancion.tipo_sancion_id == tipo_sancion_id)
    if fecha_desde:
        query = query.filter(RRHHSancion.fecha >= fecha_desde)
    if fecha_hasta:
        query = query.filter(RRHHSancion.fecha <= fecha_hasta)
    if not incluir_anuladas:
        query = query.filter(RRHHSancion.anulada.is_(False))

    total = query.count()
    items = query.order_by(RRHHSancion.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return SancionListResponse(
        items=[_sancion_to_response(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/sanciones",
    response_model=SancionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_sancion(
    body: SancionCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SancionResponse:
    """Aplicar una sanción a un empleado."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    # Validar empleado
    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == body.empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    # Validar tipo
    tipo = db.query(RRHHTipoSancion).filter(RRHHTipoSancion.id == body.tipo_sancion_id).first()
    if not tipo:
        raise HTTPException(status_code=404, detail="Tipo de sanción no encontrado")
    if not tipo.activo:
        raise HTTPException(status_code=400, detail="Tipo de sanción inactivo")

    sancion = RRHHSancion(
        empleado_id=body.empleado_id,
        tipo_sancion_id=body.tipo_sancion_id,
        fecha=body.fecha,
        motivo=body.motivo,
        descripcion=body.descripcion,
        fecha_desde=body.fecha_desde,
        fecha_hasta=body.fecha_hasta,
        aplicada_por_id=current_user.id,
    )
    db.add(sancion)
    db.commit()
    db.refresh(sancion)

    # Reload with joins
    sancion = (
        db.query(RRHHSancion)
        .options(
            joinedload(RRHHSancion.tipo_sancion),
            joinedload(RRHHSancion.empleado),
        )
        .filter(RRHHSancion.id == sancion.id)
        .first()
    )
    return _sancion_to_response(sancion)


@router.get("/sanciones/{sancion_id}", response_model=SancionResponse)
def get_sancion(
    sancion_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SancionResponse:
    """Obtener detalle de una sanción."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    sancion = (
        db.query(RRHHSancion)
        .options(
            joinedload(RRHHSancion.tipo_sancion),
            joinedload(RRHHSancion.empleado),
        )
        .filter(RRHHSancion.id == sancion_id)
        .first()
    )
    if not sancion:
        raise HTTPException(status_code=404, detail="Sanción no encontrada")

    return _sancion_to_response(sancion)


@router.patch(
    "/sanciones/{sancion_id}/anular",
    status_code=status.HTTP_204_NO_CONTENT,
)
def anular_sancion(
    sancion_id: int,
    body: SancionAnularRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Anular (dejar sin efecto) una sanción.

    Requiere motivo de anulación. No se elimina, queda marcada como anulada.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    sancion = db.query(RRHHSancion).filter(RRHHSancion.id == sancion_id).first()
    if not sancion:
        raise HTTPException(status_code=404, detail="Sanción no encontrada")

    if sancion.anulada:
        raise HTTPException(status_code=400, detail="La sanción ya está anulada")

    sancion.anulada = True
    sancion.anulada_motivo = body.motivo
    sancion.anulada_por_id = current_user.id
    sancion.anulada_at = datetime.now(UTC)
    db.commit()
