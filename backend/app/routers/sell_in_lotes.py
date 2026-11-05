"""Sell-in lot viewer per product: the lots the next sales will consume, in FIFO order, the sales each lot was
consumed by, and the product's dated cost modes, plus the preview and confirm of a mode change. Behind the permission
of the product panel, which already shows the sell-in figures; the modes, which carry typed and frozen unit costs, also
need `sell_in.ver`, and a change the mode's own permission (D7)."""

import logging
from dataclasses import replace
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user, require_algun_permiso, require_permiso
from app.api.endpoints.productos_listing import PERMISOS_VER_PRODUCTO
from app.core.database import get_db
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.schemas.sell_in_lotes import ConsumosLoteOut, LotesProductoOut
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
from app.services.sell_in import modos, visor_lotes

logger = logging.getLogger(__name__)

# Another writer held the product: deadlock_detected, lock_not_available, query_canceled (a statement_timeout while
# waiting for the product's lock). Nothing was saved; the same request can be retried. A 57014 can also be a slow
# recompute or an operator's cancel, so every mapped error is logged with its code.
OCUPADO = frozenset({"40P01", "55P03", "57014"})

# Who sold each lot (supplier, invoices) is purchase information: Productos' "Últimas compras" permission.
VER_COMPRAS = "productos.ver_info_compras"

router = APIRouter(
    prefix="/sell-in/productos",
    tags=["Sell in"],
    dependencies=[Depends(require_algun_permiso(PERMISOS_VER_PRODUCTO))],
)


@router.get(
    "/modo-por-defecto", response_model=ModoPorDefectoOut, dependencies=[Depends(require_permiso("sell_in.ver"))]
)
def modo_por_defecto(db: Session = Depends(get_db)) -> dict:
    """The cost mode the panel's selector opens preselected with (FIFO when unset). It never changes costing: a
    product without a mode row stays FIFO, and the selector still offers only the modes the user may set."""
    return {"modo": modos.modo_por_defecto(db)}


@router.put(
    "/modo-por-defecto",
    response_model=ModoPorDefectoOut,
    dependencies=[Depends(require_permiso("sell_in.ver"))],
)
def fijar_modo_por_defecto(
    body: ModoPorDefectoIn, db: Session = Depends(get_db), admin: Usuario = Depends(get_current_admin)
) -> dict:
    """Admins only: change the selector's preselected mode (audited). Nothing is recomputed."""
    return {"modo": modos.fijar_modo_por_defecto(db, body.modo, admin.id)}


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


def _validar_cambio(db: Session, usuario: Usuario, item_id: int, body: ModoIn, hoy: date) -> None:
    """422 for a mode not written here, 403 naming the permission missing (D7), 404 for an unknown product."""
    if body.modo not in modos.MODOS_ESCRITOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Cost mode '{body.modo}' cannot be set yet")
    falta = modos.permiso_faltante(body.modo, body.desde, hoy, lambda codigo: verificar_permiso(db, usuario, codigo))
    if falta is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {falta}")
    if db.query(ProductoERP.item_id).filter(ProductoERP.item_id == item_id).first() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")


def _ocupado(db: Session, exc: DBAPIError) -> HTTPException:
    """409 to retry when another writer held the product (`OCUPADO`); any other database error goes on as it was."""
    db.rollback()
    codigo = getattr(exc.orig, "pgcode", None)
    if codigo not in OCUPADO:
        raise exc
    logger.warning("sell in: a cost mode change met a busy product (%s), answered 409 to retry: %s", codigo, exc.orig)
    return HTTPException(
        status.HTTP_409_CONFLICT, "Another operation is changing the product right now: try again in a few seconds"
    )


@router.post(
    "/{item_id}/modos/vista-previa",
    response_model=VistaPreviaOut,
    dependencies=[Depends(require_permiso("sell_in.ver"))],
)
def vista_previa_modo(
    item_id: int, body: ModoIn, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)
) -> modos.VistaPrevia:
    """The mandatory preview of a mode change (D2): the recorded sales whose sell in changes and by how much, the
    units and unit value left, and the ARS the lots hold that no unit hands out. Nothing is saved; the fingerprint
    goes back with the confirm. 409 to retry when another writer held the product."""
    hoy = date.today()
    _validar_cambio(db, usuario, item_id, body, hoy)
    try:
        vista = modos.vista_previa(db, item_id, body.modo, body.desde, hoy, usuario.id)
    except ValueError as exc:  # the product's history cannot be replayed (a manual block, until it lands)
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except DBAPIError as exc:
        raise _ocupado(db, exc) from exc
    db.rollback()  # nothing to keep: the preview's savepoint was already rolled back
    return vista


@router.post(
    "/{item_id}/modos",
    response_model=ModoProductoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permiso("sell_in.ver"))],
)
def confirmar_modo(
    item_id: int, body: ModoConfirmarIn, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)
) -> modos.ModoProducto:
    """Saves the mode change the preview showed, recomputes the product and audits it. 409 when anything moved since
    the preview (a sale, a purchase, another mode row, a new day): preview again; also 409, to retry, when another
    writer held the product."""
    hoy = date.today()
    _validar_cambio(db, usuario, item_id, body, hoy)
    try:
        modo_id = modos.confirmar(db, item_id, body.modo, body.desde, hoy, usuario.id, body.huella)
    except modos.HuellaVencida as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "The product changed since the preview: preview again") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except DBAPIError as exc:
        raise _ocupado(db, exc) from exc
    db.commit()
    return next(fila for fila in modos.historial(db, item_id) if fila.id == modo_id)
