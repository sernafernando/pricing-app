"""Sell-in lot viewer per product: the lots the next sales will consume, in FIFO order, the sales each lot was
consumed by, and the product's dated cost modes, plus the preview and confirm of a mode change. Behind the permission
of the product panel, which already shows the sell-in figures; the modes, which carry typed and frozen unit costs, also
need `sell_in.ver`, and a change the mode's own permission (D7)."""

from dataclasses import replace
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user, require_algun_permiso, require_permiso
from app.api.endpoints.productos_listing import PERMISOS_VER_PRODUCTO
from app.core.database import get_db
from app.models.usuario import Usuario
from app.schemas.sell_in_lotes import ConsumosLoteOut, LotesProductoOut, ProductosCostoOut
from app.schemas.sell_in_modos import (
    ModoConfirmarIn,
    ModoIn,
    ModoPorDefectoIn,
    ModoPorDefectoOut,
    ModoProductoOut,
    ModosProductoOut,
    VistaPreviaOut,
)
from app.services.permisos_service import verificar_permiso
from app.services.sell_in import modos, productos_costo, visor_lotes

# Who sold each lot (supplier, invoices) is purchase information: Productos' "Últimas compras" permission.
VER_COMPRAS = "productos.ver_info_compras"
MODOS_RETIRADOS = "El modo de costo ya no se puede cambiar: el costo es el costo SI"

router = APIRouter(
    prefix="/sell-in/productos",
    tags=["Sell in"],
    dependencies=[Depends(require_algun_permiso(PERMISOS_VER_PRODUCTO))],
)


@router.get(
    "/modo-por-defecto", response_model=ModoPorDefectoOut, dependencies=[Depends(require_permiso("sell_in.ver"))]
)
def modo_por_defecto(db: Session = Depends(get_db)) -> dict:
    """The stored default cost mode (FIFO when unset). It only preselected the mode selector, retired with the cost
    modes (sell-in-costo-si T5 PR A): it reads, it no longer changes."""
    return {"modo": modos.modo_por_defecto(db)}


@router.put(
    "/modo-por-defecto",
    response_model=ModoPorDefectoOut,
    dependencies=[Depends(require_permiso("sell_in.ver"))],
)
def fijar_modo_por_defecto(body: ModoPorDefectoIn, admin: Usuario = Depends(get_current_admin)) -> dict:
    """Admins only, and retired like the mode changes (T5 PR A): 410, nothing stored or audited."""
    raise HTTPException(status.HTTP_410_GONE, MODOS_RETIRADOS)


@router.get("/costos", response_model=ProductosCostoOut, dependencies=[Depends(require_permiso("sell_in.ver"))])
def productos_con_costo(db: Session = Depends(get_db)) -> dict:
    """Sell in's "Productos" list: every product with units left in its lots, with its cost mode, units, the next
    sale's sell in per unit and its latest purchase, in a fixed number of queries (`productos_costo`). Writes
    nothing."""
    return {"productos": productos_costo.productos(db, date.today())}


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


@router.get("/{item_id}/modos", response_model=ModosProductoOut, dependencies=[Depends(require_permiso("sell_in.ver"))])
def modos_de_producto(item_id: int, db: Session = Depends(get_db)) -> dict:
    """The product's sell-in cost modes, newest first, and the one governing today (none: FIFO, the default)."""
    historial = modos.historial(db, item_id)
    return {"item_id": item_id, "vigente": modos.vigente(historial, date.today()), "historial": historial}


@router.post(
    "/{item_id}/modos/vista-previa",
    response_model=VistaPreviaOut,
    dependencies=[Depends(require_permiso("sell_in.ver"))],
)
def vista_previa_modo(
    item_id: int, body: ModoIn, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)
) -> modos.VistaPrevia:
    """410 always (sell-in-costo-si T5 PR A): costo SI replaced the per-product cost modes (S14), so no mode is
    previewed any more; the history still reads."""
    raise HTTPException(status.HTTP_410_GONE, MODOS_RETIRADOS)


@router.post(
    "/{item_id}/modos",
    response_model=ModoProductoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permiso("sell_in.ver"))],
)
def confirmar_modo(
    item_id: int, body: ModoConfirmarIn, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)
) -> modos.ModoProducto:
    """410 always (sell-in-costo-si T5 PR A): costo SI replaced the per-product cost modes (S14), so no mode is
    written any more; the history still reads."""
    raise HTTPException(status.HTTP_410_GONE, MODOS_RETIRADOS)
