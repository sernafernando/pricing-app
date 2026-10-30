"""The sell-in lots of a product, as the next sales will consume them (read only).

Owner: "podríamos tener un visualizador de lotes? para saber como van a aplicar?". The sell-in cost is FIFO by lot,
not weighted: each sale takes the units of the oldest line with units left, so the viewer lists a product's lines of
active purchases in that order (`costing.lotes`, sorted by `fifo.orden_fifo`) with what the stored consumptions took from
each one (`costing.unidades_usadas`) and the unit discount `split.unit_discount` gives it (a USD purchase at its own
rate, as costing converts it).

Status of a line: `vigente` is the one `costing.vigentes` returns for today (the next sale takes it); `agotado` has
no units left; `desde` counts from a date after today; `en_cola` has units left and waits behind the current one.
Nothing here is computed differently from the costing: the order, the units left and the rounding are its own.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Literal, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.models.sell_in import SellInCompra, SellInCompraPedido, SellInConsumo
from app.services.sell_in.costing import get_costing
from app.services.sell_in.split import unit_discount

Estado = Literal["vigente", "en_cola", "agotado", "desde"]


@dataclass(frozen=True)
class LoteVisor:
    numero: int  # its place in the FIFO order, from 1
    compra_item_id: int
    compra_id: int
    proveedor: Optional[str]
    facturas: List[str]  # the invoice numbers of the purchase's operations, sorted
    moneda: str  # the purchase's currency; `descuento_unit` is always ARS
    fecha_desde: date  # the date the purchase counts from
    cantidad: int
    consumidas: int
    restantes: int
    descuento_unit: Decimal  # ARS, `split.unit_discount`
    estado: Estado


@dataclass(frozen=True)
class Siguiente:
    numero: int
    descuento_unit: Decimal
    fecha_desde: date
    estado: Estado


@dataclass(frozen=True)
class ProximaVenta:
    """What the next sale gets: the current line's discount and units left, then the next line with units."""

    numero: int
    compra_item_id: int
    descuento_unit: Decimal
    restantes: int
    siguiente: Optional[Siguiente]


@dataclass(frozen=True)
class VisorLotes:
    lotes: List[LoteVisor]
    proxima: Optional[ProximaVenta]  # None: no line has units today, the cost is back to normal


@dataclass(frozen=True)
class ConsumoVisor:
    canal: str
    venta_ref: int
    fecha_venta: date
    unidades: int
    descuento_ars: Decimal


def lotes_de_producto(db: Session, item_id: int, hoy: date) -> VisorLotes:
    """The product's lines of active purchases in FIFO order, with their status on `hoy` (module docstring)."""
    costing = get_costing()
    lotes = costing.lotes(db, [item_id]).get(item_id, [])
    usadas = costing.unidades_usadas(db, [x.compra_item_id for x in lotes])
    vigente = costing.vigentes(db, [item_id], hoy).get(item_id)
    datos = _compras(db, sorted({x.compra_id for x in lotes}))
    filas: List[LoteVisor] = []
    for numero, lote in enumerate(lotes, start=1):
        consumidas = usadas.get(lote.compra_item_id, 0)
        restantes = lote.cantidad - consumidas
        if vigente is not None and lote.compra_item_id == vigente.compra_item_id:
            estado: Estado = "vigente"
        elif restantes <= 0:
            estado = "agotado"
        elif lote.fecha > hoy:
            estado = "desde"
        else:
            estado = "en_cola"
        proveedor, facturas, moneda = datos[lote.compra_id]
        filas.append(
            LoteVisor(
                numero=numero,
                compra_item_id=lote.compra_item_id,
                compra_id=lote.compra_id,
                proveedor=proveedor,
                facturas=facturas,
                moneda=moneda,
                fecha_desde=lote.fecha,
                cantidad=lote.cantidad,
                consumidas=consumidas,
                restantes=restantes,
                descuento_unit=unit_discount(lote.descuento_ars, lote.cantidad),
                estado=estado,
            )
        )
    return VisorLotes(filas, _proxima(filas))


def _proxima(filas: List[LoteVisor]) -> Optional[ProximaVenta]:
    actual = next((x for x in filas if x.estado == "vigente"), None)
    if actual is None:
        return None
    despues = next((x for x in filas[actual.numero :] if x.restantes > 0), None)
    siguiente = None
    if despues is not None:
        siguiente = Siguiente(despues.numero, despues.descuento_unit, despues.fecha_desde, despues.estado)
    return ProximaVenta(actual.numero, actual.compra_item_id, actual.descuento_unit, actual.restantes, siguiente)


def _compras(db: Session, compra_ids: List[int]) -> Dict[int, Tuple[Optional[str], List[str], str]]:
    """`{compra_id: (supplier name, invoice numbers, currency)}`. The invoices are those of the purchase's operations
    (`sell_in_compra_pedidos`) and, for a purchase a bonus generated, of the operation it came from."""
    if not compra_ids:
        return {}
    c = SellInCompra
    filas = (
        db.query(c.id, c.moneda, Proveedor.nombre)
        .outerjoin(Proveedor, Proveedor.id == c.proveedor_id)
        .filter(c.id.in_(compra_ids))
    )
    datos = {compra_id: (nombre, [], moneda) for compra_id, moneda, nombre in filas}
    pedidos = select(SellInCompraPedido.compra_id, SellInCompraPedido.pedido_compra_id.label("pedido_id")).where(
        SellInCompraPedido.compra_id.in_(compra_ids)
    )
    generadas = select(c.id, c.bono_pedido_id).where(c.id.in_(compra_ids), c.bono_pedido_id.isnot(None))
    union = pedidos.union(generadas).subquery()
    facturas = (
        db.query(union.c.compra_id, PedidoCompra.numero_factura)
        .join(PedidoCompra, PedidoCompra.id == union.c.pedido_id)
        .filter(PedidoCompra.numero_factura.isnot(None))
    )
    por_compra: Dict[int, set] = defaultdict(set)
    for compra_id, numero in facturas:
        por_compra[compra_id].add(numero)
    for compra_id, numeros in por_compra.items():
        datos[compra_id][1].extend(sorted(numeros))
    return datos


def consumos_de_lote(
    db: Session, item_id: int, compra_item_id: int, *, page: int, page_size: int
) -> Tuple[List[ConsumoVisor], int]:
    """One page of the sales that consumed the line, oldest sale first, and their total. A line of another product
    answers nothing."""
    t = SellInConsumo
    filtro = (t.compra_item_id == compra_item_id, t.item_id == item_id)
    total = db.query(func.count(t.id)).filter(*filtro).scalar() or 0
    filas = (
        db.query(t.canal, t.venta_ref, t.fecha_venta, t.unidades, t.descuento_ars)
        .filter(*filtro)
        .order_by(t.fecha_venta, t.canal, t.venta_ref, t.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [ConsumoVisor(*fila) for fila in filas], int(total)
