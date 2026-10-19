"""Search of Compras operations for the sell-in create panel's picker (T3d).

The operator picks the operations a sell in comes from instead of typing their
number. The Compras list endpoint needs Compras permissions; this read-only
search needs only `sell_in.gestionar` and answers just what identifies an
operation: number, supplier, date, currency, total, estado and invoice.

- Text (`q`): any part of the operation number, the supplier name or the
  invoice number, ignoring case (wildcards are literal); all digits also
  matches the operation id, which is what the panel's chips show.
- `proveedor_id`/`moneda` keep only the operations a sell in may still
  combine (owner decisions c and f); `excluir` drops the ones already linked.
- Newest first (`created_at`, then id), at most `OPERACIONES_LIMITE`. One
  query with the supplier joined in, no per-row lookups. The text match is a
  substring scan over a table of a few thousand rows; filters by supplier use
  `ix_pedidos_compra_proveedor_created`.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.schemas.sell_in import OPERACIONES_LIMITE
from app.services.sell_in.compras import _contiene
from app.services.sell_in.prefill import _fecha_local


def buscar_operaciones(
    db: Session,
    q: Optional[str] = None,
    proveedor_id: Optional[int] = None,
    moneda: Optional[str] = None,
    excluir: Optional[list[int]] = None,
) -> list[dict]:
    """The newest operations matching the text and filters, as the picker shows them."""
    query = db.query(PedidoCompra, Proveedor.nombre).outerjoin(Proveedor, Proveedor.id == PedidoCompra.proveedor_id)
    texto = (q or "").strip()
    if texto:
        condiciones = [
            _contiene(PedidoCompra.numero, texto),
            _contiene(Proveedor.nombre, texto),
            _contiene(PedidoCompra.numero_factura, texto),
        ]
        if texto.isdigit():
            condiciones.append(PedidoCompra.id == int(texto))
        query = query.filter(or_(*condiciones))
    if proveedor_id is not None:
        query = query.filter(PedidoCompra.proveedor_id == proveedor_id)
    if moneda is not None:
        query = query.filter(PedidoCompra.moneda == moneda)
    if excluir:
        query = query.filter(PedidoCompra.id.notin_(excluir))
    filas = query.order_by(PedidoCompra.created_at.desc(), PedidoCompra.id.desc()).limit(OPERACIONES_LIMITE)
    return [
        {
            "id": pedido.id,
            "numero": pedido.numero,
            "proveedor_id": pedido.proveedor_id,
            "proveedor_nombre": nombre,
            "fecha": _fecha_local(pedido.created_at),
            "moneda": pedido.moneda,
            "monto": pedido.monto,
            "estado": pedido.estado,
            "numero_factura": pedido.numero_factura,
        }
        for pedido, nombre in filas
    ]
