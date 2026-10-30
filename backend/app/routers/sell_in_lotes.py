"""Sell-in lot viewer per product (read only): the lots the next sales will consume, in FIFO order, and the sales
each lot was consumed by. Behind the permission of the product panel, which already shows the sell-in figures."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_algun_permiso
from app.api.endpoints.productos_listing import PERMISOS_VER_PRODUCTO
from app.core.database import get_db
from app.schemas.sell_in_lotes import ConsumosLoteOut, LotesProductoOut
from app.services.sell_in import visor_lotes

router = APIRouter(
    prefix="/sell-in/productos",
    tags=["Sell in"],
    dependencies=[Depends(require_algun_permiso(PERMISOS_VER_PRODUCTO))],
)


@router.get("/{item_id}/lotes", response_model=LotesProductoOut)
def lotes_de_producto(item_id: int, db: Session = Depends(get_db)) -> dict:
    """The product's lots of active purchases in the order the next sales take them, with today's status of each one
    and what the next sale gets (`visor_lotes`); when the lots run out (now or after the current one), the cost bonus
    that applies then, if any.
    Writes nothing."""
    hoy = date.today()
    visor = visor_lotes.lotes_de_producto(db, item_id, hoy)
    # What applies once the lots run out: now (no lot has units) or after the current one (no next lot with units).
    agotan = visor.proxima is None or visor.proxima.siguiente is None
    bono = visor_lotes.bono_costo(db, item_id, hoy) if agotan else None
    return {"item_id": item_id, "lotes": visor.lotes, "proxima": visor.proxima, "bono_costo": bono}


@router.get("/{item_id}/lotes/{compra_item_id}/consumos", response_model=ConsumosLoteOut)
def consumos_de_lote(
    item_id: int,
    compra_item_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """One page of the sales that consumed the lot, oldest first. A lot of another product answers an empty page."""
    items, total = visor_lotes.consumos_de_lote(db, item_id, compra_item_id, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}
