"""Our own product (Publicaciones ML T6, T7): read and edit the SKU and EAN of an ERP product, keyed by its `item_id`,
and copy its data (title, description, pictures, attributes) from one of its publications.

Reading needs `ml_ops.ver` (the Publicaciones ML screen); editing and choosing the source need
`ml_publicaciones.editar_producto`. The values are computed in `producto_propio_service`; only what an operator types
or copies is stored.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.models.producto_propio import MAX_CODE_LENGTH
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.services.ml_publications import admin
from app.services.ml_publications.publication_data import DatosNoValidos
from app.services.producto_propio_service import (
    FuenteNoValida,
    SinFuente,
    ProductoPropioView,
    choose_source,
    edit_datos,
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


class DatosCopiadosResponse(BaseModel):
    fuente_mla: str
    titulo: Optional[str]
    descripcion: Optional[str]
    fotos: list[dict[str, Any]]
    atributos: list[dict[str, Any]]
    copiado_at: Optional[datetime]


class ProductoPropioResponse(BaseModel):
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    ean: Optional[str]
    ean_manual: bool
    sku: Optional[str]
    sku_manual: bool
    sku_candidatos: list[str]
    datos: Optional[DatosCopiadosResponse]  # None until a source publication is chosen
    can_edit: bool


class FuenteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mla: Annotated[str, StringConstraints(pattern=admin.ITEM_ID_PATTERN)]


# The title and attribute values have no fixed ML limit across categories: only a generous cap here.
MAX_TITULO_LENGTH = 255
MAX_ATRIBUTO_VALUE_LENGTH = 255
MAX_DESCRIPCION_LENGTH = 50000  # ML's limit on a description

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AtributoEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonBlank
    value_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ATRIBUTO_VALUE_LENGTH)
    ]


class DatosRequest(BaseModel):
    """Every field is required: the edit is the whole copy, not a patch."""

    model_config = ConfigDict(extra="forbid")

    titulo: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITULO_LENGTH)]
    descripcion: Optional[Annotated[str, StringConstraints(max_length=MAX_DESCRIPCION_LENGTH)]]
    fotos: list[NonBlank]  # copied picture ids, in the new order
    atributos: list[AtributoEdit]  # copied attributes with their new value


class ProductoPropioRequest(BaseModel):
    """Both values are required: null or blank drops the manual one (back to the computed value)."""

    model_config = ConfigDict(extra="forbid")

    sku: Code
    ean: Code


def _not_found(item_id: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No se encontró el producto {item_id}")


def _response(view: ProductoPropioView, can_edit: bool) -> ProductoPropioResponse:
    return ProductoPropioResponse(**asdict(view), can_edit=can_edit)


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


@router.post("/{item_id}/fuente", response_model=ProductoPropioResponse)
def post_fuente(
    body: FuenteRequest,
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_productos_propios_db),
) -> ProductoPropioResponse:
    """Copy the title, description, pictures and attributes of `mla` onto the product, replacing an earlier copy.
    409 when `mla` is not a live publication linked to the product."""
    try:
        view = choose_source(db, item_id, body.mla, user.id)
    except FuenteNoValida as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if view is None:
        raise _not_found(item_id)
    return _response(view, True)


@router.put("/{item_id}/datos", response_model=ProductoPropioResponse)
def put_datos(
    body: DatosRequest,
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_productos_propios_db),
) -> ProductoPropioResponse:
    """Save the edited copy: title, description, the copied pictures kept (in order) and the copied attributes kept
    (with their values). 409 before a source is chosen; 422 for a picture or attribute that was not copied."""
    try:
        view = edit_datos(
            db,
            item_id,
            body.titulo,
            body.descripcion,
            body.fotos,
            [(atributo.id, atributo.value_name) for atributo in body.atributos],
            user.id,
        )
    except SinFuente as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DatosNoValidos as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if view is None:
        raise _not_found(item_id)
    return _response(view, True)
