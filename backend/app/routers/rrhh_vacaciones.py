"""
Router del módulo RRHH - Vacaciones.

Endpoints:
- Períodos: listar, generar anuales
- Solicitudes: listar, crear, aprobar, rechazar, cancelar

Ley 20.744 Art. 150 — días de vacaciones por antigüedad:
  < 5 años  → 14 días corridos
  5-10 años → 21 días corridos
  10-20 años → 28 días corridos
  > 20 años → 35 días corridos
"""

from datetime import date, datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_vacaciones import (
    RRHHVacacionesPeriodo,
    RRHHVacacionesSolicitud,
)
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.services.rrhh_vacaciones_service import VacacionesService

router = APIRouter(prefix="/rrhh/vacaciones", tags=["rrhh-vacaciones"])


# ──────────────────────────────────────────────
# SCHEMAS
# ──────────────────────────────────────────────


class PeriodoResponse(BaseModel):
    id: int
    empleado_id: int
    anio: int
    dias_correspondientes: int
    dias_gozados: int
    dias_pendientes: int
    antiguedad_anios: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Joined
    empleado_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PeriodoListResponse(BaseModel):
    items: list[PeriodoResponse]
    total: int


class GenerarPeriodosRequest(BaseModel):
    anio: int = Field(ge=2000, le=2100)


class GenerarPeriodosResponse(BaseModel):
    generados: int
    existentes: int


class SolicitudCreate(BaseModel):
    empleado_id: int
    periodo_id: int
    fecha_desde: date
    fecha_hasta: date


class SolicitudRechazarRequest(BaseModel):
    motivo: str = Field(min_length=1)


class SolicitudResponse(BaseModel):
    id: int
    empleado_id: int
    periodo_id: int
    fecha_desde: date
    fecha_hasta: date
    dias_solicitados: int
    estado: str
    motivo_rechazo: Optional[str] = None
    aprobada_por_id: Optional[int] = None
    aprobada_at: Optional[datetime] = None
    solicitada_por_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Joined
    empleado_nombre: Optional[str] = None
    periodo_anio: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class SolicitudListResponse(BaseModel):
    items: list[SolicitudResponse]
    total: int
    page: int
    page_size: int


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────


def _periodo_to_response(p: RRHHVacacionesPeriodo) -> PeriodoResponse:
    """Convert SQLAlchemy model to response, enriching with joined data."""
    data = PeriodoResponse.model_validate(p)
    if p.empleado:
        data.empleado_nombre = p.empleado.nombre_completo
    return data


def _solicitud_to_response(s: RRHHVacacionesSolicitud) -> SolicitudResponse:
    """Convert SQLAlchemy model to response, enriching with joined data."""
    data = SolicitudResponse.model_validate(s)
    if s.empleado:
        data.empleado_nombre = s.empleado.nombre_completo
    if s.periodo:
        data.periodo_anio = s.periodo.anio
    return data


# ──────────────────────────────────────────────
# ENDPOINTS — Períodos
# ──────────────────────────────────────────────


@router.get("/periodos", response_model=PeriodoListResponse)
def list_periodos(
    empleado_id: Optional[int] = Query(default=None),
    anio: Optional[int] = Query(default=None),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PeriodoListResponse:
    """Listar períodos de vacaciones. Filtros opcionales por empleado y/o año."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    query = db.query(RRHHVacacionesPeriodo).options(
        joinedload(RRHHVacacionesPeriodo.empleado),
    )

    if empleado_id:
        query = query.filter(RRHHVacacionesPeriodo.empleado_id == empleado_id)
    if anio:
        query = query.filter(RRHHVacacionesPeriodo.anio == anio)

    total = query.count()
    items = query.order_by(
        RRHHVacacionesPeriodo.anio.desc(),
        RRHHVacacionesPeriodo.empleado_id,
    ).all()

    return PeriodoListResponse(
        items=[_periodo_to_response(p) for p in items],
        total=total,
    )


@router.post(
    "/periodos/generar",
    response_model=GenerarPeriodosResponse,
    status_code=status.HTTP_201_CREATED,
)
def generar_periodos(
    body: GenerarPeriodosRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GenerarPeriodosResponse:
    """
    Generar períodos de vacaciones para todos los empleados activos.

    Calcula días según Ley 20.744 art 150 (antigüedad al 31/dic del año).
    Salta empleados que ya tienen período para ese año.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    vac_svc = VacacionesService(db)
    result = vac_svc.generar_periodos_anuales(body.anio)
    return GenerarPeriodosResponse(**result)


# ──────────────────────────────────────────────
# ENDPOINTS — Solicitudes
# ──────────────────────────────────────────────


@router.get("/solicitudes", response_model=SolicitudListResponse)
def list_solicitudes(
    empleado_id: Optional[int] = Query(default=None),
    estado: Optional[str] = Query(default=None),
    anio: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SolicitudListResponse:
    """Listar solicitudes de vacaciones con filtros opcionales."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    query = db.query(RRHHVacacionesSolicitud).options(
        joinedload(RRHHVacacionesSolicitud.empleado),
        joinedload(RRHHVacacionesSolicitud.periodo),
    )

    if empleado_id:
        query = query.filter(RRHHVacacionesSolicitud.empleado_id == empleado_id)
    if estado:
        query = query.filter(RRHHVacacionesSolicitud.estado == estado)
    if anio:
        query = query.join(RRHHVacacionesPeriodo).filter(RRHHVacacionesPeriodo.anio == anio)

    total = query.count()
    items = (
        query.order_by(RRHHVacacionesSolicitud.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    )

    return SolicitudListResponse(
        items=[_solicitud_to_response(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/solicitudes",
    response_model=SolicitudResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_solicitud(
    body: SolicitudCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SolicitudResponse:
    """
    Crear solicitud de vacaciones.

    Valida:
    - Período existe y pertenece al empleado.
    - Hay días pendientes suficientes.
    - No hay superposición con solicitudes activas.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    # Validar empleado existe
    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == body.empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    vac_svc = VacacionesService(db)
    es_valida, error_msg, dias = vac_svc.validar_solicitud(
        body.empleado_id,
        body.periodo_id,
        body.fecha_desde,
        body.fecha_hasta,
    )
    if not es_valida:
        raise HTTPException(status_code=400, detail=error_msg)

    solicitud = RRHHVacacionesSolicitud(
        empleado_id=body.empleado_id,
        periodo_id=body.periodo_id,
        fecha_desde=body.fecha_desde,
        fecha_hasta=body.fecha_hasta,
        dias_solicitados=dias,
        estado="pendiente",
        solicitada_por_id=current_user.id,
    )
    db.add(solicitud)
    db.commit()
    db.refresh(solicitud)

    # Reload with joins
    solicitud = (
        db.query(RRHHVacacionesSolicitud)
        .options(
            joinedload(RRHHVacacionesSolicitud.empleado),
            joinedload(RRHHVacacionesSolicitud.periodo),
        )
        .filter(RRHHVacacionesSolicitud.id == solicitud.id)
        .first()
    )
    return _solicitud_to_response(solicitud)


@router.patch(
    "/solicitudes/{solicitud_id}/aprobar",
    status_code=status.HTTP_204_NO_CONTENT,
)
def aprobar_solicitud(
    solicitud_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Aprobar solicitud de vacaciones.

    Actualiza el período: dias_gozados += dias_solicitados,
    dias_pendientes -= dias_solicitados.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    solicitud = (
        db.query(RRHHVacacionesSolicitud)
        .options(joinedload(RRHHVacacionesSolicitud.periodo))
        .filter(RRHHVacacionesSolicitud.id == solicitud_id)
        .first()
    )
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    if solicitud.estado != "pendiente":
        raise HTTPException(
            status_code=400,
            detail=f"Solo se pueden aprobar solicitudes pendientes (estado actual: {solicitud.estado})",
        )

    # Update solicitud
    solicitud.estado = "aprobada"
    solicitud.aprobada_por_id = current_user.id
    solicitud.aprobada_at = datetime.now(UTC)

    # Update período
    periodo = solicitud.periodo
    periodo.dias_gozados += solicitud.dias_solicitados
    periodo.dias_pendientes -= solicitud.dias_solicitados

    db.commit()


@router.patch(
    "/solicitudes/{solicitud_id}/rechazar",
    status_code=status.HTTP_204_NO_CONTENT,
)
def rechazar_solicitud(
    solicitud_id: int,
    body: SolicitudRechazarRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Rechazar solicitud de vacaciones con motivo obligatorio."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    solicitud = db.query(RRHHVacacionesSolicitud).filter(RRHHVacacionesSolicitud.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    if solicitud.estado != "pendiente":
        raise HTTPException(
            status_code=400,
            detail=f"Solo se pueden rechazar solicitudes pendientes (estado actual: {solicitud.estado})",
        )

    solicitud.estado = "rechazada"
    solicitud.motivo_rechazo = body.motivo
    db.commit()


@router.patch(
    "/solicitudes/{solicitud_id}/cancelar",
    status_code=status.HTTP_204_NO_CONTENT,
)
def cancelar_solicitud(
    solicitud_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Cancelar solicitud de vacaciones.

    Si la solicitud estaba aprobada, restaura los días al período.
    Solo se pueden cancelar solicitudes pendientes o aprobadas.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    solicitud = (
        db.query(RRHHVacacionesSolicitud)
        .options(joinedload(RRHHVacacionesSolicitud.periodo))
        .filter(RRHHVacacionesSolicitud.id == solicitud_id)
        .first()
    )
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    if solicitud.estado not in ("pendiente", "aprobada"):
        raise HTTPException(
            status_code=400,
            detail=f"Solo se pueden cancelar solicitudes pendientes o aprobadas (estado actual: {solicitud.estado})",
        )

    # If approved, restore days to period
    if solicitud.estado == "aprobada":
        periodo = solicitud.periodo
        periodo.dias_gozados -= solicitud.dias_solicitados
        periodo.dias_pendientes += solicitud.dias_solicitados

    solicitud.estado = "cancelada"
    db.commit()
