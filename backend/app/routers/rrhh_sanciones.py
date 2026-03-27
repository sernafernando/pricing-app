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
from app.models.rrhh_sancion import (
    RRHHSancion,
    RRHHTextoPredefinidoSancion,
    RRHHTipoSancion,
)
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/rrhh", tags=["rrhh-sanciones"])


# ──────────────────────────────────────────────
# PLACEHOLDERS CONOCIDOS (auto-fill desde datos del sistema)
# ──────────────────────────────────────────────

KNOWN_PLACEHOLDERS: dict[str, str] = {
    "nombre_empleado": "Nombre completo del empleado (ej: PÉREZ, JUAN)",
    "legajo": "Número de legajo",
    "dni": "DNI del empleado",
    "cuil": "CUIL del empleado",
    "area": "Área / sector del empleado",
    "puesto": "Puesto del empleado",
    "fecha_ingreso": "Fecha de ingreso (dd/mm/aaaa)",
    "tipo_sancion": "Nombre del tipo de sanción",
    "dias_suspension": "Cantidad de días de suspensión (calculado de fecha desde/hasta)",
    "fecha_sancion": "Fecha de la sanción (dd/mm/aaaa)",
    "fecha_desde": "Fecha inicio de suspensión (dd/mm/aaaa)",
    "fecha_hasta": "Fecha fin de suspensión (dd/mm/aaaa)",
}
"""Placeholders que se auto-completan con datos del empleado y la sanción.
El usuario puede usar {nombre_empleado}, {legajo}, etc. en texto_predeterminado."""


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


# ── Textos predefinidos schemas ──


class TextoPredefinidoSancionCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=200)
    texto: str = Field(min_length=1)
    orden: int = 0


class TextoPredefinidoSancionUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=200)
    texto: Optional[str] = None
    activo: Optional[bool] = None
    orden: Optional[int] = None


class TextoPredefinidoSancionResponse(BaseModel):
    id: int
    nombre: str
    texto: str
    activo: bool
    orden: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ReorderItem(BaseModel):
    id: int
    orden: int


# ── Sancion schemas ──


class SancionCreate(BaseModel):
    empleado_id: int
    tipo_sancion_id: int
    fecha: date
    motivo: str = Field(min_length=1)
    descripcion: Optional[str] = None
    texto_sancion: Optional[str] = None
    texto_predefinido_id: Optional[int] = None
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
    texto_sancion: Optional[str] = None
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    anulada: bool
    anulada_motivo: Optional[str] = None
    anulada_por_id: Optional[int] = None
    anulada_at: Optional[datetime] = None
    aplicada_por_id: int
    created_at: Optional[datetime] = None
    texto_predefinido_id: Optional[int] = None
    # Joined
    tipo_sancion_nombre: Optional[str] = None
    texto_predefinido_nombre: Optional[str] = None
    empleado_nombre: Optional[str] = None
    empleado_legajo: Optional[str] = None
    empleado_sector: Optional[str] = None

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
    if s.texto_predefinido:
        data.texto_predefinido_nombre = s.texto_predefinido.nombre
    if s.empleado:
        data.empleado_nombre = s.empleado.nombre_completo
        data.empleado_legajo = s.empleado.legajo
        data.empleado_sector = s.empleado.area
    return data


# ──────────────────────────────────────────────
# ENDPOINTS — Tipos de Sanción
# ──────────────────────────────────────────────


@router.get("/sanciones/placeholders")
def get_placeholders_sancion(
    current_user: Usuario = Depends(get_current_user),
) -> dict[str, str]:
    """Devuelve los placeholders conocidos que se auto-completan al crear sanciones."""
    return KNOWN_PLACEHOLDERS


@router.get("/tipos-sancion", response_model=list[TipoSancionResponse])
def list_tipos_sancion(
    incluir_inactivos: bool = Query(default=False),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TipoSancionResponse]:
    """Listar tipos de sanción. Por defecto solo activos."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    query = db.query(RRHHTipoSancion)
    if not incluir_inactivos:
        query = query.filter(RRHHTipoSancion.activo.is_(True))
    tipos = query.order_by(RRHHTipoSancion.orden, RRHHTipoSancion.nombre).all()
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
# ENDPOINTS — Textos Predefinidos
# ──────────────────────────────────────────────


@router.get(
    "/textos-predefinidos-sancion",
    response_model=list[TextoPredefinidoSancionResponse],
)
def list_textos_predefinidos_sancion(
    activo: Optional[bool] = Query(default=True),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TextoPredefinidoSancionResponse]:
    """Listar textos predefinidos. Por defecto solo activos."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    query = db.query(RRHHTextoPredefinidoSancion)
    if activo:
        query = query.filter(RRHHTextoPredefinidoSancion.activo.is_(True))
    textos = query.order_by(
        RRHHTextoPredefinidoSancion.orden,
        RRHHTextoPredefinidoSancion.nombre,
    ).all()
    return [TextoPredefinidoSancionResponse.model_validate(t) for t in textos]


@router.post(
    "/textos-predefinidos-sancion",
    response_model=TextoPredefinidoSancionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_texto_predefinido_sancion(
    body: TextoPredefinidoSancionCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TextoPredefinidoSancionResponse:
    """Crear texto predefinido para sanciones."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.config"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.config")

    existing = db.query(RRHHTextoPredefinidoSancion).filter(RRHHTextoPredefinidoSancion.nombre == body.nombre).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Ya existe un texto predefinido con ese nombre",
        )

    texto = RRHHTextoPredefinidoSancion(**body.model_dump())
    db.add(texto)
    db.commit()
    db.refresh(texto)
    return TextoPredefinidoSancionResponse.model_validate(texto)


# IMPORTANT: /reorder MUST be registered BEFORE /{texto_id} to avoid path conflict
@router.put("/textos-predefinidos-sancion/reorder")
def reorder_textos_predefinidos_sancion(
    items: list[ReorderItem],
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Reordenar textos predefinidos."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.config"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.config")

    for item in items:
        texto = db.query(RRHHTextoPredefinidoSancion).filter(RRHHTextoPredefinidoSancion.id == item.id).first()
        if texto:
            texto.orden = item.orden
    db.commit()
    return {"ok": True}


@router.put(
    "/textos-predefinidos-sancion/{texto_id}",
    response_model=TextoPredefinidoSancionResponse,
)
def update_texto_predefinido_sancion(
    texto_id: int,
    body: TextoPredefinidoSancionUpdate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TextoPredefinidoSancionResponse:
    """Actualizar texto predefinido (parcial)."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.config"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.config")

    texto = db.query(RRHHTextoPredefinidoSancion).filter(RRHHTextoPredefinidoSancion.id == texto_id).first()
    if not texto:
        raise HTTPException(status_code=404, detail="Texto predefinido no encontrado")

    update_data = body.model_dump(exclude_unset=True)

    # Verificar unicidad de nombre si se está cambiando
    if "nombre" in update_data and update_data["nombre"] != texto.nombre:
        conflict = (
            db.query(RRHHTextoPredefinidoSancion)
            .filter(
                RRHHTextoPredefinidoSancion.nombre == update_data["nombre"],
                RRHHTextoPredefinidoSancion.id != texto_id,
            )
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=400,
                detail="Ya existe un texto predefinido con ese nombre",
            )

    for field, value in update_data.items():
        setattr(texto, field, value)

    db.commit()
    db.refresh(texto)
    return TextoPredefinidoSancionResponse.model_validate(texto)


@router.delete(
    "/textos-predefinidos-sancion/{texto_id}",
    response_model=TextoPredefinidoSancionResponse,
)
def delete_texto_predefinido_sancion(
    texto_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TextoPredefinidoSancionResponse:
    """Soft-delete: desactivar texto predefinido (idempotente)."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.config"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.config")

    texto = db.query(RRHHTextoPredefinidoSancion).filter(RRHHTextoPredefinidoSancion.id == texto_id).first()
    if not texto:
        raise HTTPException(status_code=404, detail="Texto predefinido no encontrado")

    texto.activo = False
    db.commit()
    db.refresh(texto)
    return TextoPredefinidoSancionResponse.model_validate(texto)


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
        joinedload(RRHHSancion.texto_predefinido),
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

    # Validar texto predefinido si fue proporcionado
    if body.texto_predefinido_id is not None:
        texto_pred = (
            db.query(RRHHTextoPredefinidoSancion)
            .filter(RRHHTextoPredefinidoSancion.id == body.texto_predefinido_id)
            .first()
        )
        if not texto_pred:
            raise HTTPException(status_code=400, detail="Texto predefinido no encontrado")
        if not texto_pred.activo:
            raise HTTPException(
                status_code=400,
                detail="El texto predefinido seleccionado está inactivo",
            )

    sancion = RRHHSancion(
        empleado_id=body.empleado_id,
        tipo_sancion_id=body.tipo_sancion_id,
        fecha=body.fecha,
        motivo=body.motivo,
        descripcion=body.descripcion,
        texto_sancion=body.texto_sancion,
        texto_predefinido_id=body.texto_predefinido_id,
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
            joinedload(RRHHSancion.texto_predefinido),
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
            joinedload(RRHHSancion.texto_predefinido),
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
