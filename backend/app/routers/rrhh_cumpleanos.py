"""
Endpoints de cumpleaños de empleados.

- /rrhh/cumpleanos?mes=3&anio=2026 → empleados activos que cumplen ese mes
- /rrhh/cumpleanos/hoy → empleados activos que cumplen hoy (para topbar badge)

Solo incluye empleados activos (estado != 'baja', activo = true)
con fecha_nacimiento cargada.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import extract
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/rrhh", tags=["rrhh-cumpleanos"])


class CumpleanosEmpleado(BaseModel):
    """Empleado con datos de cumpleaños."""

    empleado_id: int
    nombre: str
    apellido: str
    legajo: str
    area: str | None = None
    fecha_nacimiento: date
    dia: int
    mes: int
    edad: int | None = None  # edad que cumple este año

    model_config = ConfigDict(from_attributes=True)


class CumpleanosHoyResponse(BaseModel):
    """Respuesta para el badge de la topbar."""

    cantidad: int
    empleados: list[CumpleanosEmpleado]


def _empleados_activos_con_nacimiento(db: Session):
    """Query base: empleados activos, sin baja, con fecha_nacimiento."""
    return db.query(RRHHEmpleado).filter(
        RRHHEmpleado.activo.is_(True),
        RRHHEmpleado.estado != "baja",
        RRHHEmpleado.fecha_nacimiento.isnot(None),
    )


def _to_cumpleanos(emp: RRHHEmpleado, anio: int) -> CumpleanosEmpleado:
    """Convierte un empleado a CumpleanosEmpleado."""
    fn = emp.fecha_nacimiento
    edad = anio - fn.year if fn else None
    return CumpleanosEmpleado(
        empleado_id=emp.id,
        nombre=emp.nombre,
        apellido=emp.apellido,
        legajo=emp.legajo,
        area=emp.area,
        fecha_nacimiento=fn,
        dia=fn.day,
        mes=fn.month,
        edad=edad,
    )


@router.get("/cumpleanos", response_model=list[CumpleanosEmpleado])
def listar_cumpleanos_mes(
    mes: int = Query(default=None, ge=1, le=12, description="Mes (1-12)"),
    anio: int = Query(default=None, description="Año para calcular edad"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CumpleanosEmpleado]:
    """
    Lista empleados activos que cumplen años en el mes indicado.
    Si no se pasa mes, usa el mes actual.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    hoy = date.today()
    if mes is None:
        mes = hoy.month
    if anio is None:
        anio = hoy.year

    empleados = (
        _empleados_activos_con_nacimiento(db)
        .filter(extract("month", RRHHEmpleado.fecha_nacimiento) == mes)
        .order_by(
            extract("day", RRHHEmpleado.fecha_nacimiento),
            RRHHEmpleado.apellido,
        )
        .all()
    )

    return [_to_cumpleanos(e, anio) for e in empleados]


@router.get("/cumpleanos/hoy", response_model=CumpleanosHoyResponse)
def cumpleanos_hoy(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CumpleanosHoyResponse:
    """
    Empleados activos que cumplen años HOY.
    Diseñado para el badge de la topbar — debe ser rápido.
    """
    # No requiere permiso rrhh.ver — cualquier usuario logueado
    # puede ver quién cumple hoy (es info social, no sensible)
    hoy = date.today()

    empleados = (
        _empleados_activos_con_nacimiento(db)
        .filter(
            extract("month", RRHHEmpleado.fecha_nacimiento) == hoy.month,
            extract("day", RRHHEmpleado.fecha_nacimiento) == hoy.day,
        )
        .order_by(RRHHEmpleado.apellido)
        .all()
    )

    items = [_to_cumpleanos(e, hoy.year) for e in empleados]
    return CumpleanosHoyResponse(cantidad=len(items), empleados=items)
