"""The invoices a tactical's invoice line applies to (sell in varias facturas S3-S5).

Owner 2026-11-13: "por defecto tendría que aplicar a todas las facturas el sell in, pero hay que hacer que se pueda
modificar eso y elegir las facturas en caso que tenga que aplicarse a una sola, dentro del propio editor".

- No pick (`tactical_linea_facturas` has no row for the line): every invoice of the operation, read from the
  aggregate snapshot `pedido_compra_lineas_facturadas`, exactly as before.
- A pick: only those invoices' buckets of the per-invoice snapshot `pedido_compra_lineas_facturadas_ct`, plus
  whatever share of the credit notes imputed to the whole operation `nc_del_pedido_para_eleccion` gives them.

The bonus engine (`bonos.reconciliar`), the invoice total (`tacticals._facturado`) and the tactical read all go
through here, so the three read the same pick.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Collection, Iterable, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_factura import PedidoCompraFactura, ct_docnumbers_by_id
from app.models.pedido_compra_linea_facturada_ct import PedidoCompraLineaFacturadaCt
from app.models.tactical import TacticalLineaFactura

Linea = tuple[int, int]  # (tactical_id, tactical_linea)


@dataclass(frozen=True)
class Facturado:
    """An item's invoiced units and net amount in one currency (amount and currency None when they cannot be added)."""

    cantidad: int
    importe_neto: Optional[Decimal]
    moneda: Optional[str]


def nc_del_pedido_para_eleccion(
    nc_del_pedido: Mapping[int, Facturado], elegidas: Collection[int], todas: Collection[int]
) -> dict[int, Facturado]:
    """THE rule for the credit notes imputed to the whole operation (no invoice of their own) when a line picks
    specific invoices: what share of them, per item, the picked invoices take (negative units and amounts).

    Current rule (option 3): they count only under "Todas" (the aggregate already nets them); a pick of specific
    invoices takes none of them.

    TODO(owner, 2026-11-13): pending decision on operation-level credit notes under a pick. Alternatives on the table:
    prorate them over the operation's invoices by units or by amount. Only this function changes; its callers already
    add whatever it returns to the picked invoices' units.
    """
    del nc_del_pedido, elegidas, todas
    return {}


def _sumar(a: Optional[Facturado], b: Facturado) -> Facturado:
    if a is None:
        return b
    mismo = a.moneda is not None and a.moneda == b.moneda and a.importe_neto is not None and b.importe_neto is not None
    return Facturado(
        a.cantidad + b.cantidad,
        a.importe_neto + b.importe_neto if mismo else None,
        a.moneda if mismo else None,
    )


def facturado_elegido(db: Session, pedido_id: int, elegidas: Collection[int]) -> dict[int, Facturado]:
    """An operation's invoiced units per item over the picked invoices only, plus the share of operation-level credit
    notes the rule gives them; the items with less than one unit left out, a negative amount clamped at 0 (like the
    aggregate)."""
    elegidas = frozenset(int(ct) for ct in elegidas)
    t = PedidoCompraLineaFacturadaCt
    por_item: dict[int, Facturado] = {}
    nc_del_pedido: dict[int, Facturado] = {}
    todas: set[int] = set()
    for ct, item_id, cantidad, importe, moneda in db.query(
        t.ct_transaction_id, t.item_id, t.cantidad, t.importe_neto, t.moneda
    ).filter(t.pedido_id == pedido_id):
        fila = Facturado(int(cantidad), Decimal(importe) if importe is not None else None, moneda)
        if ct is None:
            nc_del_pedido[int(item_id)] = fila
            continue
        todas.add(int(ct))
        if int(ct) in elegidas:
            por_item[int(item_id)] = _sumar(por_item.get(int(item_id)), fila)
    for item_id, parte in nc_del_pedido_para_eleccion(nc_del_pedido, elegidas, todas).items():
        por_item[item_id] = _sumar(por_item.get(item_id), parte)
    return {
        item_id: Facturado(
            f.cantidad, max(f.importe_neto, Decimal("0")) if f.importe_neto is not None else None, f.moneda
        )
        for item_id, f in sorted(por_item.items())
        if f.cantidad >= 1
    }


def de_lineas(db: Session, lineas: Iterable[Linea]) -> dict[Linea, frozenset[int]]:
    """The pick of each of these tactical lines; a line without one (every invoice) is absent."""
    pares = {(int(t), int(n)) for t, n in lineas if t is not None and n is not None}
    if not pares:
        return {}
    elegidas: dict[Linea, set[int]] = defaultdict(set)
    tactical_ids = {t for t, _ in pares}
    for tactical_id, numero, ct in db.query(
        TacticalLineaFactura.tactical_id, TacticalLineaFactura.tactical_linea, TacticalLineaFactura.ct_transaction_id
    ).filter(TacticalLineaFactura.tactical_id.in_(tactical_ids)):
        if (tactical_id, numero) in pares:
            elegidas[(tactical_id, numero)].add(int(ct))
    return {par: frozenset(cts) for par, cts in elegidas.items()}


def de_linea(db: Session, tactical_id: Optional[int], numero: Optional[int]) -> Optional[frozenset[int]]:
    """One line's pick; None: every invoice."""
    if tactical_id is None or numero is None:
        return None
    return de_lineas(db, [(tactical_id, numero)]).get((tactical_id, numero))


def guardar(db: Session, tactical_id: int, numero: int, cts: Optional[Iterable[int]]) -> None:
    """Store a line's pick (None or empty: every invoice, no row). Flushes, so the line's children read it."""
    for ct in sorted(set(cts or ())):
        db.add(TacticalLineaFactura(tactical_id=tactical_id, tactical_linea=numero, ct_transaction_id=ct))
    db.flush()


def borrar(db: Session, tactical_id: int) -> None:
    """Drop every pick of a tactical (a full replace stores them again)."""
    db.query(TacticalLineaFactura).filter(TacticalLineaFactura.tactical_id == tactical_id).delete(
        synchronize_session="fetch"
    )


def facturas_de(db: Session, pedido_ids: Iterable[int]) -> dict[int, list[dict]]:
    """The invoices linked to each operation, oldest link first, as the editor and the read show them:
    `{ct_transaction_id, numero, fecha_factura}`; `numero` the readable ERP number (#2264), None when the mirror has
    none. The links are `pedido_compra_facturas`, else the header's first link (`cts_for_pedido`'s rule)."""
    ids = sorted({int(p) for p in pedido_ids})
    if not ids:
        return {}
    por_pedido: dict[int, list[tuple[int, Optional[date]]]] = defaultdict(list)
    for pid, ct, fecha in (
        db.query(
            PedidoCompraFactura.pedido_id, PedidoCompraFactura.ct_transaction_id, PedidoCompraFactura.fecha_factura
        )
        .filter(PedidoCompraFactura.pedido_id.in_(ids))
        .order_by(PedidoCompraFactura.id)
    ):
        por_pedido[int(pid)].append((int(ct), fecha))
    sin_tabla = [p for p in ids if p not in por_pedido]
    if sin_tabla:
        for pid, ct, fecha in db.query(
            PedidoCompra.id, PedidoCompra.ct_transaction_id, PedidoCompra.fecha_factura
        ).filter(PedidoCompra.id.in_(sin_tabla), PedidoCompra.ct_transaction_id.isnot(None)):
            por_pedido[int(pid)].append((int(ct), fecha))
    numeros = ct_docnumbers_by_id(db, sorted({ct for links in por_pedido.values() for ct, _ in links}))
    return {
        pid: [{"ct_transaction_id": ct, "numero": numeros.get(ct), "fecha_factura": fecha} for ct, fecha in links]
        for pid, links in por_pedido.items()
    }
