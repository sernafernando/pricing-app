"""Product <-> Tienda Nube product link (abm-productos S12): the current link, the TN products to pick from (suggestions
or a search) and the link set by hand.

Reading needs `productos.ver`; changing the link needs `productos.editar_maestro` (the product master's general
section). The logic lives in `app.services.producto_tn_vinculos`.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services import producto_tn_vinculos as service
from app.services.permisos_service import PermisosService

PERMISO_VER = "productos.ver"
PERMISO_EDITAR = "productos.editar_maestro"

router = APIRouter(prefix="/producto-tn-vinculos", tags=["Vínculo producto - Tienda Nube"])


def get_producto_tn_db(db: Session = Depends(get_db)) -> Session:
    """The session the product and TN tables are read and written through: the request's own. A separate dependency
    only so a test can point those tables at a Postgres store."""
    return db


class TnProducto(BaseModel):
    tn_product_id: int
    nombre: Optional[str]
    skus: list[str]
    precio: Optional[float]  # the lowest variant price
    published: Optional[bool]
    item_id: Optional[int]  # the ERP product its variants carry today


class VinculoResponse(BaseModel):
    item_id: int
    origen: Optional[Literal["manual", "sku"]]  # None: not linked
    tn: Optional[TnProducto]  # None: not linked (with origen "manual": set as not linked by hand)
    can_edit: bool


class Candidato(TnProducto):
    motivo: Literal["ean", "nombre", "busqueda"]


class VincularRequest(BaseModel):
    tn_product_id: Optional[int]  # required; null = "Desvincular"


def _read(store_db: Session, item_id: int, can_edit: bool) -> VinculoResponse:
    try:
        vinculo = service.vinculo_actual(store_db, item_id)
    except service.ProductoNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Producto {item_id} no encontrado") from exc
    return VinculoResponse(item_id=item_id, can_edit=can_edit, **vinculo)


@router.get("/{item_id}", response_model=VinculoResponse)
def leer(
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_VER)),
    db: Session = Depends(get_db),
    store_db: Session = Depends(get_producto_tn_db),
) -> VinculoResponse:
    """The TN product the product is linked to, and whether it was set by hand or by the sync's SKU match."""
    return _read(store_db, item_id, PermisosService(db).tiene_permiso(user, PERMISO_EDITAR))


@router.get("/{item_id}/candidatos", response_model=list[Candidato])
def candidatos(
    item_id: int = Path(..., ge=1),
    q: Optional[str] = Query(None, max_length=100),
    _user: Usuario = Depends(require_permiso(PERMISO_VER)),
    store_db: Session = Depends(get_producto_tn_db),
) -> list[Candidato]:
    """Without `q`, the suggestions (same EAN first, then a similar name); with `q`, the active TN products whose
    name or SKU contains it."""
    try:
        return [Candidato(**c) for c in service.candidatos(store_db, item_id, q)]
    except service.ProductoNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Producto {item_id} no encontrado") from exc


@router.put("/{item_id}", response_model=VinculoResponse)
def vincular(
    body: VincularRequest,
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    store_db: Session = Depends(get_producto_tn_db),
) -> VinculoResponse:
    """Links the product to a TN product by hand (`null`: explicitly not linked). It applies at once and every sync
    keeps it. A TN product linked by hand to another product is refused (409)."""
    try:
        service.guardar_vinculo(store_db, item_id, body.tn_product_id, user.id)
    except service.ProductoNoEncontrado as exc:
        store_db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Producto {item_id} no encontrado") from exc
    except service.TnProductoNoEncontrado as exc:
        store_db.rollback()
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Producto de Tienda Nube {body.tn_product_id} no encontrado"
        ) from exc
    except service.TnYaVinculado as exc:
        store_db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Ese producto de Tienda Nube ya está vinculado a mano al producto {exc.item_id}",
        ) from exc
    store_db.commit()
    return _read(store_db, item_id, can_edit=True)
