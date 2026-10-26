"""Our own product (Publicaciones ML T6): read and edit the SKU and EAN of an ERP product, keyed by its `item_id`.

Reading needs `ml_ops.ver` (the Publicaciones ML screen); editing needs `ml_publicaciones.editar_producto`. The values
are computed in `producto_propio_service`; only what an operator types is stored.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.models.producto_propio import MAX_CODE_LENGTH
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.services.producto_propio_service import (
    ProductoPropioView,
    read_producto_propio,
    save_producto_propio,
)

PERMISO_VER = "ml_ops.ver"
PERMISO_EDITAR = "ml_publicaciones.editar_producto"

router = APIRouter(prefix="/productos-propios", tags=["Productos propios"])

# Trimmed before the length check: surrounding spaces typed in the panel do not count against the column width.
Code = Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_CODE_LENGTH)]]


def get_productos_propios_db(db: Session = Depends(get_db)) -> Session:
    """The session the product tables are read and written through: the request's own (same database as the
    permission check). A separate dependency only so a test can point those tables elsewhere."""
    return db


class ProductoPropioResponse(BaseModel):
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    ean: Optional[str]
    ean_manual: bool
    sku: Optional[str]
    sku_manual: bool
    sku_candidatos: list[str]
    can_edit: bool


class ProductoPropioRequest(BaseModel):
    """Both values are required: null or blank drops the manual one (back to the computed value)."""

    model_config = ConfigDict(extra="forbid")

    sku: Code
    ean: Code


def _not_found(item_id: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No se encontró el producto {item_id}")


def _response(view: ProductoPropioView, can_edit: bool) -> ProductoPropioResponse:
    return ProductoPropioResponse(**vars(view), can_edit=can_edit)


@router.get("/{item_id}", response_model=ProductoPropioResponse)
def get_producto_propio(
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_VER)),
    auth_db: Session = Depends(get_db),
    db: Session = Depends(get_productos_propios_db),
) -> ProductoPropioResponse:
    """The product's SKU and EAN, which of them are manual, the SKUs its publications carry, and whether the user
    may edit them."""
    view = read_producto_propio(db, item_id)
    if view is None:
        raise _not_found(item_id)
    return _response(view, PermisosService(auth_db).tiene_permiso(user, PERMISO_EDITAR))


@router.put("/{item_id}", response_model=ProductoPropioResponse)
def put_producto_propio(
    body: ProductoPropioRequest,
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_productos_propios_db),
) -> ProductoPropioResponse:
    """Set the manual SKU and EAN (null or blank drops each one) and answer the values the panel now shows."""
    view = save_producto_propio(db, item_id, body.sku, body.ean, user.id)
    if view is None:
        raise _not_found(item_id)
    return _response(view, True)
