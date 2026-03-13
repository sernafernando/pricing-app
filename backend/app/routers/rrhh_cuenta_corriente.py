"""
Router del módulo RRHH - Cuenta Corriente + Herramientas.

Endpoints:
- Cuentas corrientes: listar, detalle con movimientos, cargo, abono, liquidación
- Herramientas: listar por empleado, asignar, devolver

Convención de saldo:
  Positivo = el empleado DEBE (deuda)
  Negativo = la empresa debe al empleado (crédito)
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.rrhh_cuenta_corriente import (
    RRHHCuentaCorriente,
    RRHHCuentaCorrienteMovimiento,
)
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_herramienta import RRHHAsignacionHerramienta
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.services.rrhh_cuenta_corriente_service import CuentaCorrienteService

router = APIRouter(prefix="/rrhh", tags=["rrhh-cuenta-corriente"])


# ──────────────────────────────────────────────
# SCHEMAS — Cuenta Corriente
# ──────────────────────────────────────────────


class CuentaResumenResponse(BaseModel):
    """Resumen de cuenta corriente con datos del empleado."""

    id: int
    empleado_id: int
    empleado_nombre: str = ""
    empleado_legajo: str = ""
    saldo: float
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MovimientoResponse(BaseModel):
    """Movimiento individual de cuenta corriente."""

    id: int
    cuenta_id: int
    empleado_id: int
    tipo: str
    monto: float
    fecha: date
    concepto: str
    descripcion: Optional[str] = None
    item_id: Optional[int] = None
    ct_transaction: Optional[int] = None
    cuota_numero: Optional[int] = None
    cuota_total: Optional[int] = None
    saldo_posterior: float
    registrado_por_nombre: str = ""
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CuentaDetalleResponse(BaseModel):
    """Detalle de cuenta corriente con movimientos paginados."""

    empleado_id: int
    empleado_nombre: str = ""
    empleado_legajo: str = ""
    saldo: float
    movimientos: list[MovimientoResponse] = []
    total_movimientos: int = 0


class CargoCreate(BaseModel):
    """Datos para registrar un cargo (compra)."""

    monto: float = Field(gt=0, description="Monto de la compra")
    concepto: str = Field(min_length=1, max_length=255)
    descripcion: Optional[str] = Field(default=None, max_length=2000)
    item_id: Optional[int] = None
    ct_transaction: Optional[int] = None
    cuotas: int = Field(default=1, ge=1, le=48, description="Cantidad de cuotas")


class AbonoCreate(BaseModel):
    """Datos para registrar un abono (pago/deducción)."""

    monto: float = Field(gt=0, description="Monto del abono")
    concepto: str = Field(min_length=1, max_length=255)
    descripcion: Optional[str] = Field(default=None, max_length=2000)


class LiquidacionRequest(BaseModel):
    """Datos para ejecutar la liquidación mensual."""

    mes: int = Field(ge=1, le=12)
    anio: int = Field(ge=2020, le=2100)


class LiquidacionResponse(BaseModel):
    """Resultado de la liquidación mensual."""

    procesados: int
    abonos_generados: int
    monto_total: float


# ──────────────────────────────────────────────
# SCHEMAS — Herramientas
# ──────────────────────────────────────────────


class HerramientaCreate(BaseModel):
    """Datos para asignar una herramienta."""

    empleado_id: int
    descripcion: str = Field(min_length=1, max_length=255)
    codigo_inventario: Optional[str] = Field(default=None, max_length=100)
    item_id: Optional[int] = None
    cantidad: int = Field(default=1, ge=1)
    fecha_asignacion: date
    observaciones: Optional[str] = Field(default=None, max_length=2000)


class HerramientaResponse(BaseModel):
    """Respuesta de herramienta asignada."""

    id: int
    empleado_id: int
    empleado_nombre: str = ""
    descripcion: str
    codigo_inventario: Optional[str] = None
    item_id: Optional[int] = None
    cantidad: int
    fecha_asignacion: date
    fecha_devolucion: Optional[date] = None
    estado: str
    observaciones: Optional[str] = None
    asignado_por_nombre: str = ""
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────


def _check_permiso(db: Session, user: Usuario, codigo: str) -> None:
    """Verifica permiso o lanza 403."""
    if not PermisosService(db).tiene_permiso(user, codigo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sin permiso: {codigo}",
        )


def _get_empleado_or_404(db: Session, empleado_id: int) -> RRHHEmpleado:
    """Obtiene empleado o lanza 404."""
    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == empleado_id).first()
    if not empleado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Empleado {empleado_id} no encontrado",
        )
    return empleado


# ──────────────────────────────────────────────
# ENDPOINTS — Cuenta Corriente
# ──────────────────────────────────────────────


@router.get(
    "/cuenta-corriente",
    response_model=list[CuentaResumenResponse],
    summary="Listar cuentas corrientes con saldo",
)
def listar_cuentas_corrientes(
    search: Optional[str] = Query(None, description="Buscar por nombre o legajo"),
    solo_con_saldo: bool = Query(False, description="Solo cuentas con saldo != 0"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[CuentaResumenResponse]:
    """Lista todas las cuentas corrientes con datos del empleado."""
    _check_permiso(db, current_user, "rrhh.ver")

    query = db.query(RRHHCuentaCorriente).options(joinedload(RRHHCuentaCorriente.empleado))

    if solo_con_saldo:
        query = query.filter(RRHHCuentaCorriente.saldo != 0)

    cuentas = query.order_by(RRHHCuentaCorriente.empleado_id).all()

    result = []
    for cuenta in cuentas:
        emp = cuenta.empleado
        if search:
            search_lower = search.lower()
            nombre_completo = f"{emp.nombre} {emp.apellido}".lower()
            if search_lower not in nombre_completo and search_lower not in (emp.legajo or "").lower():
                continue

        result.append(
            CuentaResumenResponse(
                id=cuenta.id,
                empleado_id=cuenta.empleado_id,
                empleado_nombre=f"{emp.apellido}, {emp.nombre}",
                empleado_legajo=emp.legajo or "",
                saldo=float(cuenta.saldo),
                updated_at=cuenta.updated_at,
            )
        )

    return result


@router.get(
    "/cuenta-corriente/{empleado_id}",
    response_model=CuentaDetalleResponse,
    summary="Detalle de cuenta corriente con movimientos",
)
def detalle_cuenta_corriente(
    empleado_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CuentaDetalleResponse:
    """Detalle de cuenta corriente con movimientos paginados."""
    _check_permiso(db, current_user, "rrhh.ver")
    empleado = _get_empleado_or_404(db, empleado_id)

    # Obtener o crear cuenta (lazy)
    svc = CuentaCorrienteService(db)
    cuenta = svc.obtener_o_crear_cuenta(empleado_id)
    db.commit()  # commit lazy creation if needed

    # Query movimientos
    mov_query = (
        db.query(RRHHCuentaCorrienteMovimiento)
        .options(joinedload(RRHHCuentaCorrienteMovimiento.registrado_por))
        .filter(RRHHCuentaCorrienteMovimiento.cuenta_id == cuenta.id)
    )

    if fecha_desde:
        mov_query = mov_query.filter(RRHHCuentaCorrienteMovimiento.fecha >= fecha_desde)
    if fecha_hasta:
        mov_query = mov_query.filter(RRHHCuentaCorrienteMovimiento.fecha <= fecha_hasta)

    total = mov_query.count()
    offset = (page - 1) * page_size
    movimientos = (
        mov_query.order_by(RRHHCuentaCorrienteMovimiento.created_at.desc()).offset(offset).limit(page_size).all()
    )

    return CuentaDetalleResponse(
        empleado_id=empleado_id,
        empleado_nombre=f"{empleado.apellido}, {empleado.nombre}",
        empleado_legajo=empleado.legajo or "",
        saldo=float(cuenta.saldo),
        total_movimientos=total,
        movimientos=[
            MovimientoResponse(
                id=m.id,
                cuenta_id=m.cuenta_id,
                empleado_id=m.empleado_id,
                tipo=m.tipo,
                monto=float(m.monto),
                fecha=m.fecha,
                concepto=m.concepto,
                descripcion=m.descripcion,
                item_id=m.item_id,
                ct_transaction=m.ct_transaction,
                cuota_numero=m.cuota_numero,
                cuota_total=m.cuota_total,
                saldo_posterior=float(m.saldo_posterior),
                registrado_por_nombre=(m.registrado_por.nombre if m.registrado_por else ""),
                created_at=m.created_at,
            )
            for m in movimientos
        ],
    )


@router.post(
    "/cuenta-corriente/{empleado_id}/cargo",
    response_model=MovimientoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar cargo (compra de empleado)",
)
def registrar_cargo(
    empleado_id: int,
    data: CargoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> MovimientoResponse:
    """Registra una compra (cargo) en la cuenta corriente del empleado."""
    _check_permiso(db, current_user, "rrhh.gestionar")
    _get_empleado_or_404(db, empleado_id)

    svc = CuentaCorrienteService(db)
    try:
        movimiento = svc.registrar_cargo(
            empleado_id=empleado_id,
            monto=Decimal(str(data.monto)),
            concepto=data.concepto,
            registrado_por_id=current_user.id,
            descripcion=data.descripcion,
            item_id=data.item_id,
            ct_transaction=data.ct_transaction,
            cuotas=data.cuotas,
        )
        db.commit()
        db.refresh(movimiento)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return MovimientoResponse(
        id=movimiento.id,
        cuenta_id=movimiento.cuenta_id,
        empleado_id=movimiento.empleado_id,
        tipo=movimiento.tipo,
        monto=float(movimiento.monto),
        fecha=movimiento.fecha,
        concepto=movimiento.concepto,
        descripcion=movimiento.descripcion,
        item_id=movimiento.item_id,
        ct_transaction=movimiento.ct_transaction,
        cuota_numero=movimiento.cuota_numero,
        cuota_total=movimiento.cuota_total,
        saldo_posterior=float(movimiento.saldo_posterior),
        registrado_por_nombre=current_user.nombre,
        created_at=movimiento.created_at,
    )


@router.post(
    "/cuenta-corriente/{empleado_id}/abono",
    response_model=MovimientoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar abono (pago/deducción)",
)
def registrar_abono(
    empleado_id: int,
    data: AbonoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> MovimientoResponse:
    """Registra un pago/deducción (abono) en la cuenta corriente del empleado."""
    _check_permiso(db, current_user, "rrhh.gestionar")
    _get_empleado_or_404(db, empleado_id)

    svc = CuentaCorrienteService(db)
    try:
        movimiento = svc.registrar_abono(
            empleado_id=empleado_id,
            monto=Decimal(str(data.monto)),
            concepto=data.concepto,
            registrado_por_id=current_user.id,
            descripcion=data.descripcion,
        )
        db.commit()
        db.refresh(movimiento)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return MovimientoResponse(
        id=movimiento.id,
        cuenta_id=movimiento.cuenta_id,
        empleado_id=movimiento.empleado_id,
        tipo=movimiento.tipo,
        monto=float(movimiento.monto),
        fecha=movimiento.fecha,
        concepto=movimiento.concepto,
        descripcion=movimiento.descripcion,
        item_id=movimiento.item_id,
        ct_transaction=movimiento.ct_transaction,
        cuota_numero=movimiento.cuota_numero,
        cuota_total=movimiento.cuota_total,
        saldo_posterior=float(movimiento.saldo_posterior),
        registrado_por_nombre=current_user.nombre,
        created_at=movimiento.created_at,
    )


@router.post(
    "/cuenta-corriente/liquidacion-mensual",
    response_model=LiquidacionResponse,
    summary="Ejecutar liquidación mensual de cuotas",
)
def liquidacion_mensual(
    data: LiquidacionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> LiquidacionResponse:
    """
    Genera abonos mensuales automáticos para empleados con cuotas pendientes.

    Busca cargos con cuotas > 1 y genera el abono correspondiente
    a la siguiente cuota no pagada.
    """
    _check_permiso(db, current_user, "rrhh.gestionar")

    svc = CuentaCorrienteService(db)
    resultado = svc.liquidacion_mensual(
        mes=data.mes,
        anio=data.anio,
        registrado_por_id=current_user.id,
    )
    db.commit()

    return LiquidacionResponse(
        procesados=resultado["procesados"],
        abonos_generados=resultado["abonos_generados"],
        monto_total=float(resultado["monto_total"]),
    )


# ──────────────────────────────────────────────
# ENDPOINTS — Herramientas
# ──────────────────────────────────────────────


@router.get(
    "/herramientas/{empleado_id}",
    response_model=list[HerramientaResponse],
    summary="Listar herramientas asignadas a un empleado",
)
def listar_herramientas(
    empleado_id: int,
    estado: Optional[str] = Query(None, description="Filtrar por estado: asignado, devuelto, perdido, roto"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[HerramientaResponse]:
    """Lista herramientas asignadas a un empleado."""
    _check_permiso(db, current_user, "rrhh.ver")
    empleado = _get_empleado_or_404(db, empleado_id)

    query = (
        db.query(RRHHAsignacionHerramienta)
        .options(
            joinedload(RRHHAsignacionHerramienta.empleado),
            joinedload(RRHHAsignacionHerramienta.asignado_por),
        )
        .filter(RRHHAsignacionHerramienta.empleado_id == empleado_id)
    )

    if estado:
        estados_validos = ["asignado", "devuelto", "perdido", "roto"]
        if estado not in estados_validos:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Estado inválido. Opciones: {', '.join(estados_validos)}",
            )
        query = query.filter(RRHHAsignacionHerramienta.estado == estado)

    herramientas = query.order_by(RRHHAsignacionHerramienta.fecha_asignacion.desc()).all()

    return [
        HerramientaResponse(
            id=h.id,
            empleado_id=h.empleado_id,
            empleado_nombre=f"{empleado.apellido}, {empleado.nombre}",
            descripcion=h.descripcion,
            codigo_inventario=h.codigo_inventario,
            item_id=h.item_id,
            cantidad=h.cantidad,
            fecha_asignacion=h.fecha_asignacion,
            fecha_devolucion=h.fecha_devolucion,
            estado=h.estado,
            observaciones=h.observaciones,
            asignado_por_nombre=(h.asignado_por.nombre if h.asignado_por else ""),
            created_at=h.created_at,
        )
        for h in herramientas
    ]


@router.post(
    "/herramientas",
    response_model=HerramientaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar herramienta a empleado",
)
def asignar_herramienta(
    data: HerramientaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> HerramientaResponse:
    """Asigna una herramienta o equipamiento a un empleado."""
    _check_permiso(db, current_user, "rrhh.gestionar")
    empleado = _get_empleado_or_404(db, data.empleado_id)

    herramienta = RRHHAsignacionHerramienta(
        empleado_id=data.empleado_id,
        descripcion=data.descripcion,
        codigo_inventario=data.codigo_inventario,
        item_id=data.item_id,
        cantidad=data.cantidad,
        fecha_asignacion=data.fecha_asignacion,
        estado="asignado",
        observaciones=data.observaciones,
        asignado_por_id=current_user.id,
    )
    db.add(herramienta)
    db.commit()
    db.refresh(herramienta)

    return HerramientaResponse(
        id=herramienta.id,
        empleado_id=herramienta.empleado_id,
        empleado_nombre=f"{empleado.apellido}, {empleado.nombre}",
        descripcion=herramienta.descripcion,
        codigo_inventario=herramienta.codigo_inventario,
        item_id=herramienta.item_id,
        cantidad=herramienta.cantidad,
        fecha_asignacion=herramienta.fecha_asignacion,
        fecha_devolucion=herramienta.fecha_devolucion,
        estado=herramienta.estado,
        observaciones=herramienta.observaciones,
        asignado_por_nombre=current_user.nombre,
        created_at=herramienta.created_at,
    )


@router.patch(
    "/herramientas/{herramienta_id}/devolver",
    response_model=HerramientaResponse,
    summary="Marcar herramienta como devuelta",
)
def devolver_herramienta(
    herramienta_id: int,
    fecha_devolucion: Optional[date] = None,
    observaciones: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> HerramientaResponse:
    """Marca una herramienta como devuelta."""
    _check_permiso(db, current_user, "rrhh.gestionar")

    herramienta = (
        db.query(RRHHAsignacionHerramienta)
        .options(
            joinedload(RRHHAsignacionHerramienta.empleado),
            joinedload(RRHHAsignacionHerramienta.asignado_por),
        )
        .filter(RRHHAsignacionHerramienta.id == herramienta_id)
        .first()
    )
    if not herramienta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Herramienta {herramienta_id} no encontrada",
        )
    if herramienta.estado == "devuelto":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La herramienta ya fue devuelta",
        )

    herramienta.estado = "devuelto"
    herramienta.fecha_devolucion = fecha_devolucion or date.today()
    if observaciones:
        herramienta.observaciones = observaciones

    db.commit()
    db.refresh(herramienta)

    emp = herramienta.empleado
    return HerramientaResponse(
        id=herramienta.id,
        empleado_id=herramienta.empleado_id,
        empleado_nombre=f"{emp.apellido}, {emp.nombre}" if emp else "",
        descripcion=herramienta.descripcion,
        codigo_inventario=herramienta.codigo_inventario,
        item_id=herramienta.item_id,
        cantidad=herramienta.cantidad,
        fecha_asignacion=herramienta.fecha_asignacion,
        fecha_devolucion=herramienta.fecha_devolucion,
        estado=herramienta.estado,
        observaciones=herramienta.observaciones,
        asignado_por_nombre=(herramienta.asignado_por.nombre if herramienta.asignado_por else ""),
        created_at=herramienta.created_at,
    )
