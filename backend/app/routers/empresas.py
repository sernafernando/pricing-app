"""
Router CRUD de Empresas propias del grupo.

Administrable desde el panel Admin.
Requiere permiso: config (para crear/editar/desactivar).
Lectura (listar): cualquier usuario autenticado.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.empresa import Empresa
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/admin", tags=["admin-empresas"])


# ── Schemas ──────────────────────────────────────


class EmpresaCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    razon_social: Optional[str] = Field(default=None, max_length=255)
    cuit: Optional[str] = Field(default=None, max_length=20)
    direccion: Optional[str] = Field(default=None, max_length=500)
    telefono: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    notas: Optional[str] = None
    activo: bool = True
    orden: int = 0


class EmpresaResponse(BaseModel):
    id: int
    nombre: str
    razon_social: Optional[str] = None
    cuit: Optional[str] = None
    direccion: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    notas: Optional[str] = None
    activo: bool
    orden: int

    model_config = ConfigDict(from_attributes=True)


# ── Endpoints ────────────────────────────────────


@router.get("/empresas", response_model=list[EmpresaResponse])
def listar_empresas(
    activo: Optional[bool] = Query(default=None),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EmpresaResponse]:
    """Lista empresas. Filtro opcional por activo. Cualquier usuario autenticado."""
    query = db.query(Empresa)
    if activo is not None:
        query = query.filter(Empresa.activo == activo)
    return query.order_by(Empresa.orden, Empresa.nombre).all()


@router.post(
    "/empresas",
    response_model=EmpresaResponse,
    status_code=status.HTTP_201_CREATED,
)
def crear_empresa(
    body: EmpresaCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmpresaResponse:
    """Crear una empresa. Requiere permiso config."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "config"):
        raise HTTPException(status_code=403, detail="Sin permiso: config")

    existente = db.query(Empresa).filter(Empresa.nombre == body.nombre).first()
    if existente:
        raise HTTPException(status_code=400, detail=f"Ya existe una empresa con nombre '{body.nombre}'")

    empresa = Empresa(**body.model_dump())
    db.add(empresa)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.put("/empresas/{empresa_id}", response_model=EmpresaResponse)
def actualizar_empresa(
    empresa_id: int,
    body: EmpresaCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmpresaResponse:
    """Actualizar una empresa. Requiere permiso config."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "config"):
        raise HTTPException(status_code=403, detail="Sin permiso: config")

    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    for field, value in body.model_dump().items():
        setattr(empresa, field, value)
    db.commit()
    db.refresh(empresa)
    return empresa
