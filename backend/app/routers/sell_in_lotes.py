"""Sell-in lot viewer per product (read only): the lots the next sales will consume, in FIFO order, and the sales
each lot was consumed by. Behind the permission of the product panel, which already shows the sell-in figures."""

from dataclasses import replace
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_algun_permiso
from app.api.endpoints.productos_listing import PERMISOS_VER_PRODUCTO
from app.core.database import get_db
from app.models.usuario import Usuario
from app.schemas.sell_in_lotes import ConsumosLoteOut, LotesProductoOut
from app.services.permisos_service import verificar_permiso
from app.services.sell_in import visor_lotes

# Who sold each lot (supplier, invoices) is purchase information: Productos' "Últimas compras" permission.
VER_COMPRAS = "productos.ver_info_compras"

router = APIRouter(
    prefix="/sell-in/productos",
    tags=["Sell in"],
    dependencies=[Depends(require_algun_permiso(PERMISOS_VER_PRODUCTO))],
)


@router.get("/{item_id}/lotes", response_model=LotesProductoOut)
def lotes_de_producto(
    item_id: int, current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """The product's lots of active purchases in the order the next sales take them, with today's status of each one
    and what the next sale gets (`visor_lotes`); while no lot has units (now, after the current one, or until a next
    lot that counts from a future date), the cost bonus that applies then, if any. The supplier and invoices only with `productos.ver_info_compras` (`compra_visible`).
    Writes nothing."""
    hoy = date.today()
    visor = visor_lotes.lotes_de_producto(db, item_id, hoy)
    # What applies once the lots run out: now (no lot has units), after the current one (no next lot with units), or
    # between the current one and a next lot that counts from a future date.
    siguiente = visor.proxima.siguiente if visor.proxima else None
    agotan = visor.proxima is None or siguiente is None or siguiente.estado == "desde"
    bono = visor_lotes.bono_costo(db, item_id, hoy) if agotan else None
    compra_visible = verificar_permiso(db, current_user, VER_COMPRAS)
    lotes = visor.lotes if compra_visible else [replace(x, proveedor=None, facturas=[]) for x in visor.lotes]
    return {
        "item_id": item_id,
        "lotes": lotes,
        "proxima": visor.proxima,
        "bono_costo": bono,
        "compra_visible": compra_visible,
    }


@router.get("/{item_id}/lotes/{compra_item_id}/consumos", response_model=ConsumosLoteOut)
def consumos_de_lote(
    item_id: int,
    compra_item_id: int,
    page: int = Query(1, ge=1, le=1_000_000),  # bounds the SQL OFFSET (page x page_size) far below bigint
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """One page of the sales that consumed the lot, oldest first. A lot of another product answers an empty page."""
    items, total = visor_lotes.consumos_de_lote(db, item_id, compra_item_id, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}
