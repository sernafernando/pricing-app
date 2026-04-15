"""
Router: Administración — Bancos de la empresa.

CRUD de cuentas bancarias propias de la empresa.
Base para el futuro módulo de caja/tesorería.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.banco_empresa import BancoEmpresa
from app.models.usuario import Usuario
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


class BancoEmpresaListResponse(BaseModel):
    bancos: list[BancoEmpresaResponse]
    total: int


# =============================================================================
# HELPERS
# =============================================================================


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    svc = PermisosService(db)
    if not svc.tiene_permiso(user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("", response_model=BancoEmpresaListResponse)
def listar_bancos(
    solo_activos: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BancoEmpresaListResponse:
    """Lista las cuentas bancarias de la empresa."""
    _check_permiso(db, current_user, "administracion.ver_proveedores")

    query = db.query(BancoEmpresa)
    if solo_activos:
        query = query.filter(BancoEmpresa.activo == True)  # noqa: E712

    bancos = query.order_by(BancoEmpresa.banco).all()
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
    """Obtiene una cuenta bancaria por ID."""
    _check_permiso(db, current_user, "administracion.ver_proveedores")

    banco = db.query(BancoEmpresa).filter(BancoEmpresa.id == banco_id).first()
    if not banco:
        raise HTTPException(status_code=404, detail="Cuenta bancaria no encontrada")
    return BancoEmpresaResponse.model_validate(banco)


@router.post("", response_model=BancoEmpresaResponse, status_code=status.HTTP_201_CREATED)
def crear_banco(
    data: BancoEmpresaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BancoEmpresaResponse:
    """Crea una cuenta bancaria."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    # Verificar CBU duplicado
    if data.cbu:
        existing = db.query(BancoEmpresa).filter(BancoEmpresa.cbu == data.cbu).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe una cuenta con CBU {data.cbu}: {existing.banco}",
            )

    banco = BancoEmpresa(**data.model_dump())
    db.add(banco)
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
    """Actualiza una cuenta bancaria."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    banco = db.query(BancoEmpresa).filter(BancoEmpresa.id == banco_id).first()
    if not banco:
        raise HTTPException(status_code=404, detail="Cuenta bancaria no encontrada")

    update_data = data.model_dump(exclude_unset=True)

    # Verificar CBU duplicado si cambia
    new_cbu = update_data.get("cbu")
    if new_cbu:
        existing = db.query(BancoEmpresa).filter(BancoEmpresa.cbu == new_cbu, BancoEmpresa.id != banco_id).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe una cuenta con CBU {new_cbu}: {existing.banco}",
            )

    for field, value in update_data.items():
        setattr(banco, field, value)

    db.commit()
    db.refresh(banco)
    return BancoEmpresaResponse.model_validate(banco)
