"""
Router: Administración — Impuestos de la empresa.

ABM de impuestos, retenciones y percepciones con alícuotas.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.impuesto_empresa import ImpuestoEmpresa
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

router = APIRouter(
    prefix="/administracion/impuestos",
    tags=["Administración - Impuestos"],
)


# =============================================================================
# SCHEMAS
# =============================================================================


class ImpuestoResponse(BaseModel):
    id: int
    nombre: str
    tipo: str
    codigo_afip: Optional[int] = None
    alicuota: float
    aplica_a: str = "ambos"
    notas: Optional[str] = None
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ImpuestoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)
    tipo: str = Field(min_length=1, max_length=50)  # iva, retencion, percepcion, otro
    codigo_afip: Optional[int] = None
    alicuota: float = Field(ge=0, le=100)
    aplica_a: str = Field("ambos", max_length=20)  # compras, ventas, ambos
    notas: Optional[str] = None


class ImpuestoUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=255)
    tipo: Optional[str] = Field(None, min_length=1, max_length=50)
    codigo_afip: Optional[int] = None
    alicuota: Optional[float] = Field(None, ge=0, le=100)
    aplica_a: Optional[str] = Field(None, max_length=20)
    notas: Optional[str] = None
    activo: Optional[bool] = None


class ImpuestoListResponse(BaseModel):
    impuestos: list[ImpuestoResponse]
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


@router.get("", response_model=ImpuestoListResponse)
async def listar_impuestos(
    solo_activos: bool = Query(True),
    tipo: Optional[str] = Query(None, description="Filtrar por tipo: iva, retencion, percepcion, otro"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ImpuestoListResponse:
    """Lista los impuestos/retenciones/percepciones configurados."""
    _check_permiso(db, current_user, "administracion.ver_proveedores")

    query = db.query(ImpuestoEmpresa)
    if solo_activos:
        query = query.filter(ImpuestoEmpresa.activo == True)  # noqa: E712
    if tipo:
        query = query.filter(ImpuestoEmpresa.tipo == tipo)

    impuestos = query.order_by(ImpuestoEmpresa.tipo, ImpuestoEmpresa.nombre).all()
    return ImpuestoListResponse(
        impuestos=[ImpuestoResponse.model_validate(i) for i in impuestos],
        total=len(impuestos),
    )


@router.get("/{impuesto_id}", response_model=ImpuestoResponse)
async def obtener_impuesto(
    impuesto_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ImpuestoResponse:
    """Obtiene un impuesto por ID."""
    _check_permiso(db, current_user, "administracion.ver_proveedores")

    imp = db.query(ImpuestoEmpresa).filter(ImpuestoEmpresa.id == impuesto_id).first()
    if not imp:
        raise HTTPException(status_code=404, detail="Impuesto no encontrado")
    return ImpuestoResponse.model_validate(imp)


@router.post("", response_model=ImpuestoResponse, status_code=status.HTTP_201_CREATED)
async def crear_impuesto(
    data: ImpuestoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ImpuestoResponse:
    """Crea un impuesto/retención/percepción."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    imp = ImpuestoEmpresa(**data.model_dump())
    db.add(imp)
    db.commit()
    db.refresh(imp)
    return ImpuestoResponse.model_validate(imp)


@router.put("/{impuesto_id}", response_model=ImpuestoResponse)
async def actualizar_impuesto(
    impuesto_id: int,
    data: ImpuestoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ImpuestoResponse:
    """Actualiza un impuesto/retención/percepción."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    imp = db.query(ImpuestoEmpresa).filter(ImpuestoEmpresa.id == impuesto_id).first()
    if not imp:
        raise HTTPException(status_code=404, detail="Impuesto no encontrado")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(imp, field, value)

    db.commit()
    db.refresh(imp)
    return ImpuestoResponse.model_validate(imp)
