"""Router: sell-in purchases (`/api/sell-in/compras`), feature sell-in-sell-out T2.

A sell-in purchase is a purchase discount spread over the items it covers; it
lowers the cost of THAT purchase's units only. The math lives in
`app.services.sell_in` (split + `compras`); this module is HTTP only.

- Reads (`GET ""`, `GET /{id}`) need `sell_in.ver`; the preview, the load and
  the void need `sell_in.gestionar` (migration `20261025_sell_in_permisos`).
- `POST /preview` writes nothing. `POST ""` recomputes the same split
  server-side, freezes each line's base cost and records the author from the
  token, never from the body.
- `GET ""` is paginated, newest purchase date first, filtered by item,
  supplier, estado, an inclusive purchase-date range, `aplica`, free text
  (`q`), item brands (`marcas`, CSV, exact) and currency. Every purchase carries
  its supplier name, its `aplica` flag and its lines with consumed and remaining
  units (from `sell_in_consumos`).
- A purchase may come from several Compras operations (`pedido_compra_ids`; the
  legacy single `pedido_compra_id` still works): they must exist and share the
  supplier and currency, which the purchase must match. `GET /prefill` (needs
  `sell_in.gestionar`) suggests supplier, currency, receipt date and products
  from them (`app.services.sell_in.prefill`). `GET /operaciones` (same
  permission, no Compras permission needed) searches them for the panel's
  picker (`app.services.sell_in.operaciones`); `GET /operaciones/{id}/productos`
  (same permission) lists one operation's products for the picker's popover.
- `GET /resumen` takes the same filters and returns exact aggregates over every
  matching purchase (bucket counts, amount per currency, units covered).
- Business-rule errors are a 422 with one readable Spanish message; an unknown
  purchase is a 404.
- There is no delete and no edit: a wrong purchase is voided (`POST /{id}/anular`,
  with an optional reason kept in the audit rows; 409 if it already was) and
  loaded again. Whether lines can be edited once units have been consumed is a
  later decision, deliberately left out here.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.sell_in import SellInCompra
from app.models.usuario import Usuario
from app.schemas.sell_in import (
    PEDIDOS_MAX,
    Aplica,
    Estado,
    Moneda,
    SellInAnularIn,
    SellInCompraCreate,
    SellInCompraListOut,
    SellInCompraOut,
    SellInCompraResumenOut,
    SellInOperacionesOut,
    SellInOperacionProductosOut,
    SellInPrefillOut,
    SellInPreviewIn,
    SellInPreviewOut,
)
from app.services.permisos_service import verificar_permiso
from app.services.sell_in import compras as service
from app.services.sell_in import operaciones as operaciones_service
from app.services.sell_in import prefill as prefill_service

router = APIRouter(prefix="/sell-in/compras", tags=["Sell in"])


def _forbidden(codigo: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes permiso: {codigo}")


def requiere_ver(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> Usuario:
    if not verificar_permiso(db, current_user, "sell_in.ver"):
        raise _forbidden("sell_in.ver")
    return current_user


def requiere_gestionar(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> Usuario:
    if not verificar_permiso(db, current_user, "sell_in.gestionar"):
        raise _forbidden("sell_in.gestionar")
    return current_user


def _unprocessable(exc: service.SellInError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post("/preview", response_model=SellInPreviewOut)
def preview_compra(
    data: SellInPreviewIn,
    _user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """How the total would be split, with each line's cost without and with sell in. Writes nothing."""
    try:
        return service.calcular_preview(db, data)
    except service.SellInError as exc:
        raise _unprocessable(exc) from exc


@router.post("", response_model=SellInCompraOut, status_code=status.HTTP_201_CREATED)
def crear_compra(
    data: SellInCompraCreate,
    user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    try:
        compra = service.crear_compra(db, data, user.id)
    except service.SellInError as exc:
        db.rollback()
        raise _unprocessable(exc) from exc
    return service.serializar(db, [compra])[0]


def filtros_compras(
    item_id: Optional[int] = Query(None),
    proveedor_id: Optional[int] = Query(None),
    estado: Optional[Estado] = Query(None),
    fecha_desde: Optional[date] = Query(None, description="Purchase date, inclusive"),
    fecha_hasta: Optional[date] = Query(None, description="Purchase date, inclusive"),
    aplica: Optional[Aplica] = Query(None, description="si | no | todas (default: todas)"),
    q: Optional[str] = Query(
        None,
        max_length=200,
        description="Free text: supplier name, items' code or description, purchase reference or order number",
    ),
    marcas: Optional[str] = Query(None, description="CSV of item brands, exact match"),
    moneda: Optional[Moneda] = Query(None),
) -> service.FiltrosCompras:
    """The filters shared by the list and its summary."""
    lista_marcas = [m.strip() for m in (marcas or "").split(",") if m.strip()]
    return service.FiltrosCompras(
        item_id=item_id,
        proveedor_id=proveedor_id,
        estado=estado,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        aplica=aplica,
        q=q,
        marcas=lista_marcas or None,
        moneda=moneda,
    )


@router.get("", response_model=SellInCompraListOut)
def listar_compras(
    filtros: service.FiltrosCompras = Depends(filtros_compras),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user: Usuario = Depends(requiere_ver),
    db: Session = Depends(get_db),
) -> dict:
    compras, total = service.listar_compras(db, filtros, page=page, page_size=page_size)
    return {"items": service.serializar(db, compras), "total": total, "page": page, "page_size": page_size}


@router.get("/resumen", response_model=SellInCompraResumenOut)
def resumir_compras(
    filtros: service.FiltrosCompras = Depends(filtros_compras),
    _user: Usuario = Depends(requiere_ver),
    db: Session = Depends(get_db),
) -> dict:
    """Totals for the summary cards over EVERY purchase matching the list filters (not a page)."""
    return service.resumir_compras(db, filtros)


@router.get("/prefill", response_model=SellInPrefillOut)
def prefill_compra(
    pedido_compra_ids: list[int] = Query(default_factory=list, max_length=PEDIDOS_MAX),
    _user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """Supplier, currency, receipt date and products of Compras operations, to start a load from. Writes nothing."""
    try:
        return prefill_service.prefill(db, pedido_compra_ids)
    except service.SellInError as exc:
        raise _unprocessable(exc) from exc


@router.get("/operaciones", response_model=SellInOperacionesOut)
def buscar_operaciones(
    q: Optional[str] = Query(None, max_length=100, description="Operation number or id, supplier name or invoice"),
    proveedor_id: Optional[int] = Query(None),
    moneda: Optional[Moneda] = Query(None),
    excluir: list[int] = Query(default_factory=list, max_length=PEDIDOS_MAX, description="Operations already linked"),
    _user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """The newest Compras operations matching the text, for the create panel's picker. Writes nothing."""
    return {"items": operaciones_service.buscar_operaciones(db, q, proveedor_id, moneda, excluir)}


@router.get("/operaciones/{pedido_id}/productos", response_model=SellInOperacionProductosOut)
def productos_operacion(
    pedido_id: int,
    _user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """The products of one Compras operation (ordered and received units), for the picker's popover."""
    items = prefill_service.productos_operacion(db, pedido_id)
    if items is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"La operación {pedido_id} no existe")
    return {"items": items}


@router.get("/{compra_id}", response_model=SellInCompraOut)
def obtener_compra(
    compra_id: int,
    _user: Usuario = Depends(requiere_ver),
    db: Session = Depends(get_db),
) -> dict:
    compra = db.get(SellInCompra, compra_id)
    if compra is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"La compra {compra_id} no existe")
    return service.serializar(db, [compra])[0]


@router.post("/{compra_id}/anular", response_model=SellInCompraOut)
def anular_compra(
    compra_id: int,
    data: Optional[SellInAnularIn] = Body(None),
    user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """Void the purchase (the reason goes to the audit rows). A second call is a 409, and so is a
    purchase generated by a brand bonus (only the bonus changes it)."""
    try:
        compra = service.anular_compra(db, compra_id, user.id, data.motivo if data else None)
    except (service.SellInYaAnulada, service.SellInGenerada) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if compra is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"La compra {compra_id} no existe")
    return service.serializar(db, [compra])[0]
