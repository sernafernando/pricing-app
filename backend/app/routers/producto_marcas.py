"""Brands ABM (abm-productos L10): list, create own brands, rename (override over GBP) and deactivate. Same rules as the
categories ABM, without a Tienda Nube link. Reading needs `productos.ver`; writing needs `productos.editar_categorias`.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.models.usuario import Usuario
from app.routers.producto_categorias import PERMISO_EDITAR, PERMISO_VER, CrearRequest, Fila, ejecutar
from app.services import producto_categorias as service

router = APIRouter(prefix="/producto-marcas", tags=["Marcas de productos"])


class EditarMarcaRequest(BaseModel):
    """Only the fields sent change. `nombre: null` goes back to GBP's name."""

    nombre: Optional[str] = Field(None, max_length=service.NOMBRE_MAX)
    activa: Optional[bool] = None


@router.get("", response_model=list[Fila])
def listar(
    _user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Every brand, active or not, with its GBP and local names and product count."""
    return service.listar_marcas(db)


@router.post("", response_model=Fila, status_code=status.HTTP_201_CREATED)
def crear(
    body: CrearRequest,
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create an own brand (id from 1,000,000 up, never sent to GBP)."""
    return ejecutar(db, lambda: service.crear_marca(db, body.nombre, user.id))


@router.patch("/{marca_id}", response_model=Fila)
def editar(
    body: EditarMarcaRequest,
    marca_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Rename (null = back to GBP) or (de)activate a brand; it is never deleted."""
    cambios = body.model_dump(include=body.model_fields_set)
    return ejecutar(db, lambda: service.editar_marca(db, marca_id, cambios, user.id))
