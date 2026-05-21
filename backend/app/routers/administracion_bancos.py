"""
Router: Administración — Bancos de la empresa.

CRUD de cuentas bancarias propias de la empresa + movimientos (ledger).

Permisos (F7 fix — eran *_proveedores por error):
  - Lectura: administracion.ver_caja
  - Escritura: administracion.gestionar_caja
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.banco_empresa import BancoEmpresa
from app.models.usuario import Usuario
from app.services.banco_service import BancoService
from app.services.permisos_service import PermisosService

router = APIRouter(
    prefix="/administracion/bancos",
    tags=["Administración - Bancos"],
)


# =============================================================================
# SCHEMAS
# =============================================================================


class BancoEmpresaResponse(BaseModel):
    id: int
    banco: str
    tipo_cuenta: Optional[str] = None
    cbu: Optional[str] = None
    alias: Optional[str] = None
    numero_cuenta: Optional[str] = None
    sucursal: Optional[str] = None
    moneda: str = "ARS"
    titular: Optional[str] = None
    cuit_titular: Optional[str] = None
    saldo_inicial: float = 0
    saldo_actual: float = 0  # F7: running balance
    empresa_id: Optional[int] = None  # F7: empresa assignment (AD-13)
    notas: Optional[str] = None
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BancoEmpresaCreate(BaseModel):
    banco: str = Field(min_length=1, max_length=255)
    tipo_cuenta: Optional[str] = Field(None, max_length=50)
    cbu: Optional[str] = Field(None, max_length=30)
    alias: Optional[str] = Field(None, max_length=100)
    numero_cuenta: Optional[str] = Field(None, max_length=50)
    sucursal: Optional[str] = Field(None, max_length=100)
    moneda: str = Field("ARS", max_length=10)
    titular: Optional[str] = Field(None, max_length=255)
    cuit_titular: Optional[str] = Field(None, max_length=20)
    saldo_inicial: float = 0
    notas: Optional[str] = None
    empresa_id: Optional[int] = None  # F7: empresa assignment


class BancoEmpresaUpdate(BaseModel):
    banco: Optional[str] = Field(None, min_length=1, max_length=255)
    tipo_cuenta: Optional[str] = Field(None, max_length=50)
    cbu: Optional[str] = Field(None, max_length=30)
    alias: Optional[str] = Field(None, max_length=100)
    numero_cuenta: Optional[str] = Field(None, max_length=50)
    sucursal: Optional[str] = Field(None, max_length=100)
    moneda: Optional[str] = Field(None, max_length=10)
    titular: Optional[str] = Field(None, max_length=255)
    cuit_titular: Optional[str] = Field(None, max_length=20)
    saldo_inicial: Optional[float] = None
    notas: Optional[str] = None
    activo: Optional[bool] = None
    empresa_id: Optional[int] = None  # F7: empresa assignment


class BancoEmpresaListResponse(BaseModel):
    bancos: list[BancoEmpresaResponse]
    total: int


class BancoMovimientoCreate(BaseModel):
    fecha: date
    detalle: str = Field(min_length=1, max_length=500)
    tipo: str = Field(pattern="^(ingreso|egreso)$")
    monto: Decimal = Field(gt=0)
    observaciones: Optional[str] = None


class BancoMovimientoResponse(BaseModel):
    id: int
    banco_id: int
    fecha: date
    detalle: str
    tipo: str
    monto: float
    saldo_posterior: float
    origen: str
    observaciones: Optional[str] = None
    registrado_por_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BancoMovimientosListResponse(BaseModel):
    items: list[BancoMovimientoResponse]
    total: int
    page: int
    page_size: int
    total_ingresos: float
    total_egresos: float
    saldo_periodo: float


# =============================================================================
# HELPERS
# =============================================================================


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    svc = PermisosService(db)
    if not svc.tiene_permiso(user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


# =============================================================================
# ENDPOINTS — BancoEmpresa CRUD
# =============================================================================


@router.get("", response_model=BancoEmpresaListResponse)
def listar_bancos(
    solo_activos: bool = Query(True),
    empresa_id: Optional[int] = Query(None),  # F7: filter by empresa_id
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BancoEmpresaListResponse:
    """Lista las cuentas bancarias de la empresa. Requiere administracion.ver_caja."""
    _check_permiso(db, current_user, "administracion.ver_caja")

    svc = BancoService(db)
    activo_filter: Optional[bool] = True if solo_activos else None
    bancos = svc.listar_bancos(activo=activo_filter, empresa_id=empresa_id)
    return BancoEmpresaListResponse(
        bancos=[BancoEmpresaResponse.model_validate(b) for b in bancos],
        total=len(bancos),
    )


@router.get("/{banco_id}", response_model=BancoEmpresaResponse)
def obtener_banco(
    banco_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BancoEmpresaResponse:
    """Obtiene una cuenta bancaria por ID. Requiere administracion.ver_caja."""
    _check_permiso(db, current_user, "administracion.ver_caja")

    svc = BancoService(db)
    banco = svc.obtener_banco(banco_id)
    return BancoEmpresaResponse.model_validate(banco)


@router.post("", response_model=BancoEmpresaResponse, status_code=status.HTTP_201_CREATED)
def crear_banco(
    data: BancoEmpresaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BancoEmpresaResponse:
    """Crea una cuenta bancaria. Requiere administracion.gestionar_caja."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")

    # Check CBU uniqueness
    if data.cbu:
        existing = db.query(BancoEmpresa).filter(BancoEmpresa.cbu == data.cbu).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe una cuenta con CBU {data.cbu}: {existing.banco}",
            )

    svc = BancoService(db)
    banco = svc.crear_banco(
        banco=data.banco,
        empresa_id=data.empresa_id,
        moneda=data.moneda,
        saldo_inicial=Decimal(str(data.saldo_inicial)),
        tipo_cuenta=data.tipo_cuenta,
        cbu=data.cbu,
        alias=data.alias,
        numero_cuenta=data.numero_cuenta,
        sucursal=data.sucursal,
        titular=data.titular,
        cuit_titular=data.cuit_titular,
        notas=data.notas,
    )
    db.commit()
    db.refresh(banco)
    return BancoEmpresaResponse.model_validate(banco)


@router.put("/{banco_id}", response_model=BancoEmpresaResponse)
def actualizar_banco(
    banco_id: int,
    data: BancoEmpresaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BancoEmpresaResponse:
    """Actualiza una cuenta bancaria. Requiere administracion.gestionar_caja."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")

    # Check CBU uniqueness if changing
    if data.cbu:
        existing = (
            db.query(BancoEmpresa)
            .filter(
                BancoEmpresa.cbu == data.cbu,
                BancoEmpresa.id != banco_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe una cuenta con CBU {data.cbu}: {existing.banco}",
            )

    update_data = data.model_dump(exclude_unset=True)
    svc = BancoService(db)

    # empresa_id needs sentinel handling: only pass if explicitly in payload
    has_empresa_id = "empresa_id" in update_data
    empresa_id_val = update_data.pop("empresa_id", None)

    banco = svc.actualizar_banco(
        banco_id=banco_id,
        **update_data,
        **({} if not has_empresa_id else {"empresa_id": empresa_id_val}),
    )
    db.commit()
    db.refresh(banco)
    return BancoEmpresaResponse.model_validate(banco)


# =============================================================================
# ENDPOINTS — BancoMovimiento
# =============================================================================


@router.get("/{banco_id}/movimientos", response_model=BancoMovimientosListResponse)
def listar_movimientos(
    banco_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    tipo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BancoMovimientosListResponse:
    """Lista movimientos de una cuenta bancaria. Requiere administracion.ver_caja."""
    _check_permiso(db, current_user, "administracion.ver_caja")

    svc = BancoService(db)
    # Ensure banco exists
    svc.obtener_banco(banco_id)

    items, total, summary = svc.obtener_movimientos(
        banco_id=banco_id,
        page=page,
        page_size=page_size,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tipo=tipo,
    )
    return BancoMovimientosListResponse(
        items=[BancoMovimientoResponse.model_validate(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
        total_ingresos=summary["total_ingresos"],
        total_egresos=summary["total_egresos"],
        saldo_periodo=summary["saldo_periodo"],
    )


@router.post(
    "/{banco_id}/movimientos",
    response_model=BancoMovimientoResponse,
    status_code=status.HTTP_201_CREATED,
)
def registrar_movimiento(
    banco_id: int,
    data: BancoMovimientoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BancoMovimientoResponse:
    """Registra un movimiento manual en una cuenta bancaria. Requiere administracion.gestionar_caja."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")

    svc = BancoService(db)
    movimiento = svc.registrar_movimiento(
        banco_id=banco_id,
        fecha=data.fecha,
        detalle=data.detalle,
        tipo=data.tipo,
        monto=data.monto,
        user_id=current_user.id,
        observaciones=data.observaciones,
        origen="manual",
    )
    db.commit()
    db.refresh(movimiento)
    return BancoMovimientoResponse.model_validate(movimiento)
