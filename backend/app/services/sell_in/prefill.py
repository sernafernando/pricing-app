"""What a sell in's Compras operations say about it, to start the load from (T3b-2).

The operations (`pedidos_compra`) give the supplier and the currency (checked
by `compras.operaciones`, the same rules a load enforces), the goods-receipt
date and the products with their quantities. Everything is a suggestion: the
operator edits it and the load stores what was sent, so costing never reads
the ERP mirror afterwards.

- Products: the lines of the ERP purchase orders linked to the operations
  (`pedido_compra_ocs`, else the header's first-link cache, via
  `triples_for_pedido`) in `tb_purchase_order_detail`, one row per product,
  in the order of their first line. Lines without a product are left out.
- Quantity: the SUM of `pod_qty`, the ordered quantity. A sell in covers the
  units the supplier is crediting, which is what was ordered; `pod_confirmedqty`
  is what has been received so far and is still 0 for a purchase loaded
  before its goods arrive (`oc_ingresos_service`: pending = pod_qty - confirmed).
- Receipt date: the earliest goods receipt of the operations
  (`pedido_compra_ingresos`, sentinel arrival rows included): its
  `fecha_ingreso` when typed, else the Buenos Aires date of `created_at` (the
  reception service does not fill `fecha_ingreso`). None without receipts.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.pedido_compra_ingresos import PedidoCompraIngreso
from app.models.pedido_compra_oc import triples_for_pedido
from app.models.producto import ProductoERP
from app.models.proveedor import Proveedor
from app.models.purchase_order_detail import PurchaseOrderDetail
from app.services.sell_in.compras import SellInError, operaciones

_TZ_LOCAL = ZoneInfo("America/Argentina/Buenos_Aires")


def _fecha_local(momento: datetime) -> date:
    if momento.tzinfo is None:  # SQLite drops the zone; the column is UTC
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(_TZ_LOCAL).date()


def _fecha_ingreso(db: Session, pedido_ids: list[int]) -> Optional[date]:
    filas = db.query(PedidoCompraIngreso.fecha_ingreso, PedidoCompraIngreso.created_at).filter(
        PedidoCompraIngreso.pedido_id.in_(pedido_ids)
    )
    fechas = [tipeada or _fecha_local(creada) for tipeada, creada in filas]
    return min(fechas, default=None)


def _items(db: Session, pedidos) -> list[dict]:
    triples = list(dict.fromkeys(t for pedido in pedidos for t in triples_for_pedido(db, pedido)))
    if not triples:
        return []
    d = PurchaseOrderDetail
    lineas = (
        db.query(d.item_id, d.pod_qty)
        .filter(
            or_(*(and_(d.comp_id == c, d.bra_id == b, d.poh_id == p) for c, b, p in triples)),
            d.item_id.isnot(None),
        )
        .order_by(d.comp_id, d.bra_id, d.poh_id, d.pod_id)
    )
    cantidades: dict[int, Decimal] = {}
    for item_id, qty in lineas:
        cantidades[item_id] = cantidades.get(item_id, Decimal("0")) + Decimal(str(qty or 0))
    productos = {p.item_id: p for p in db.query(ProductoERP).filter(ProductoERP.item_id.in_(list(cantidades)))}
    items = []
    for item_id, total in cantidades.items():
        cantidad = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))  # a sell-in line counts whole units
        if cantidad <= 0:
            continue
        producto = productos.get(item_id)
        items.append(
            {
                "item_id": item_id,
                "codigo": producto.codigo if producto else None,
                "descripcion": producto.descripcion if producto else None,
                "cantidad": cantidad,
            }
        )
    return items


def prefill(db: Session, pedido_compra_ids: list[int]) -> dict:
    """Supplier, currency, receipt date and products of the operations; `SellInError` when they do not fit."""
    ids = list(dict.fromkeys(pedido_compra_ids))
    ops = operaciones(db, ids)
    if ops is None:
        raise SellInError("Indicá al menos una operación de compra")
    proveedor = db.get(Proveedor, ops.proveedor_id)
    return {
        "pedido_compra_ids": ids,
        "proveedor_id": ops.proveedor_id,
        "proveedor_nombre": proveedor.nombre if proveedor else None,
        "moneda": ops.moneda,
        "fecha_ingreso": _fecha_ingreso(db, ids),
        "items": _items(db, ops.pedidos),
    }
