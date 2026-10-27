"""What a bonus reaches, for its panel (sell-in-sell-out T3c-4; scopes in T3e-3; `sin_aplicar` in T18).

"Of the brand" below means of the bonus's scope: its brand, its category, its
models, or only its own operation for an invoice bonus (`_del_alcance`).

Four groups, each capped at `limite` rows with its full count:

- `alcanzadas`: the ACTIVE sell-in purchases the worker generated for the bonus
  (`origen = 'bono_marca'`), with their units and amount; latest invoice first.
- `pendientes`: operations of the brand with no supplier invoice date yet
  (`pedidos_compra.fecha_factura` NULL). Before invoicing there are no invoiced
  lines, so the brand is known from what was RECEIVED (`pedido_compra_ingresos`):
  an operation not received yet does not show here. Its units are the received
  ones, as information; the bonus pays on the invoiced ones. Newest first.
- `fuera_de_rango`: operations of the brand invoiced outside the bonus range,
  from the invoiced-lines snapshot (`pedido_compra_lineas_facturadas`, net of
  credit notes), with the brand's invoiced units; latest invoice first.
- `sin_aplicar`: operations of the brand invoiced INSIDE the range with no active
  generated purchase, which no other group shows. "Of the brand" by the snapshot
  or, when the snapshot has none of it, by what was received. Each says why
  (`motivo`): the worker's error and attempts when the operation's or the bonus's
  key is parked in `sell_in_bono_dirty` with an error; that the invoice has no
  line of the scope when the snapshot has none; otherwise "En cola" (the worker
  has not run on it yet). Units are the brand's invoiced ones; latest invoice first.

Cancelled or rejected operations never show (`bonos.ESTADOS_EXCLUIDOS`; a
corrected operation is cancelled). The brand match is exact on
`productos_erp.marca`, like the reconcile. Read-only, two queries per group
(three for `sin_aplicar`: rows, count, and one for the queue), none per row.
ERP independence (owner, 2026-10-17): only app tables, never `tb_*`.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, func, literal, or_, select, true, union_all
from sqlalchemy.orm import Query, Session

from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_ingresos import PedidoCompraIngreso
from app.models.pedido_compra_linea_facturada import PedidoCompraLineaFacturada
from app.models.producto import ProductoERP
from app.models.proveedor import Proveedor
from app.models.sell_in import SellInBonoDirty, SellInBonoItem, SellInBonoMarca, SellInCompra, SellInCompraItem
from app.services.sell_in.bonos import ESTADOS_EXCLUIDOS, ORIGEN


def _grupo(query: Query, limite: int, fila) -> dict:
    return {"total": query.order_by(None).count(), "items": [fila(row) for row in query.limit(limite)]}


def _unidades(total) -> int:
    """Whole units, rounded half up like the prefill (`prefill.py`): received units are NUMERIC(18, 6)."""
    return int(Decimal(str(total)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _pedido(row) -> dict:
    return {
        "pedido_id": row.id,
        "numero": row.numero,
        "proveedor_nombre": row.proveedor_nombre,
        "numero_factura": row.numero_factura,
        "fecha_factura": row.fecha_factura,
        "unidades": _unidades(row.unidades),
    }


def _pedidos_de_marca(db: Session, unidades_por_pedido) -> Query:
    """Live operations joined to their brand units (a subquery `pedido_id, unidades`) and supplier."""
    return (
        db.query(
            PedidoCompra.id,
            PedidoCompra.numero,
            PedidoCompra.numero_factura,
            PedidoCompra.fecha_factura,
            Proveedor.nombre.label("proveedor_nombre"),
            unidades_por_pedido.c.unidades,
        )
        .join(unidades_por_pedido, unidades_por_pedido.c.pedido_id == PedidoCompra.id)
        .outerjoin(Proveedor, Proveedor.id == PedidoCompra.proveedor_id)
        .filter(PedidoCompra.estado.notin_(ESTADOS_EXCLUIDOS))
    )


def _del_alcance(db: Session, bono: SellInBonoMarca, item_id, pedido_id):
    """The rows (a product joined, its `item_id` and `pedido_id` columns) the bonus's scope reaches, like the
    reconcile (`bonos._alcanzadas`)."""
    if bono.alcance == "categoria":
        return ProductoERP.categoria == bono.categoria
    if bono.alcance == "modelos":
        return item_id.in_(db.query(SellInBonoItem.item_id).filter(SellInBonoItem.bono_id == bono.id))
    if bono.alcance == "factura":
        return pedido_id == bono.pedido_id if bono.pedido_id is not None else ~true()
    return ProductoERP.marca == bono.marca


MOTIVO_EN_COLA = "En cola"
MOTIVO_SIN_LINEAS = {
    "marca": "Sin líneas de la marca en la factura",
    "categoria": "Sin líneas de la categoría en la factura",
    "modelos": "Sin líneas de los modelos en la factura",
    "factura": "La factura no tiene líneas facturadas",
}
MOTIVO_MAX = 200  # chars of a queued error shown in the panel


def _error_legible(error: str) -> str:
    """One line, collapsed whitespace, capped: a driver error can carry a multi-line DETAIL and the SQL."""
    texto = " ".join(error.split())
    return texto if len(texto) <= MOTIVO_MAX else texto[: MOTIVO_MAX - 1] + "…"


def _sin_aplicar(db: Session, bono: SellInBonoMarca, facturadas, recibidas, limite: int) -> dict:
    """In-range operations of the scope with no active generated purchase, each with its `motivo`.

    The scope is the union of the snapshot (`facturadas`) and what was received (`recibidas`), so an invoice
    whose snapshot holds no line of the scope still shows (with 0 units) instead of falling in no group."""
    del_alcance = union_all(
        select(facturadas.c.pedido_id, facturadas.c.unidades),
        select(recibidas.c.pedido_id, literal(0).label("unidades")),
    ).subquery()
    unidades = (
        db.query(del_alcance.c.pedido_id.label("pedido_id"), func.sum(del_alcance.c.unidades).label("unidades"))
        .group_by(del_alcance.c.pedido_id)
        .subquery()
    )
    aplicada = (
        db.query(SellInCompra.id)
        .filter(
            SellInCompra.bono_id == bono.id,
            SellInCompra.bono_pedido_id == PedidoCompra.id,
            SellInCompra.origen == ORIGEN,
            SellInCompra.estado == "activa",
        )
        .exists()
    )
    query = (
        _pedidos_de_marca(db, unidades)
        .filter(
            PedidoCompra.fecha_factura.isnot(None),
            PedidoCompra.fecha_factura >= bono.fecha_desde,
            PedidoCompra.fecha_factura <= bono.fecha_hasta,
            ~aplicada,
        )
        .order_by(PedidoCompra.fecha_factura.desc(), PedidoCompra.id.desc())
    )
    filas = query.limit(limite).all()

    # The queue keys that explain them: each listed operation's, and the bonus's own. One query.
    claves = [and_(SellInBonoDirty.tipo == "bono", SellInBonoDirty.ref == bono.id)]
    if filas:
        claves.append(and_(SellInBonoDirty.tipo == "pedido", SellInBonoDirty.ref.in_([f.id for f in filas])))
    en_cola = {(d.tipo, d.ref): d for d in db.query(SellInBonoDirty).filter(or_(*claves))}
    del_bono = en_cola.get(("bono", bono.id))
    sin_lineas = MOTIVO_SIN_LINEAS.get(bono.alcance, MOTIVO_SIN_LINEAS["marca"])

    def fila(row) -> dict:
        item = _pedido(row)
        # The operation's own key first: it is the more specific failure.
        clave = en_cola.get(("pedido", row.id)) or del_bono
        es_error = clave is not None and bool(clave.last_error)
        if es_error:
            motivo = _error_legible(clave.last_error)
        elif item["unidades"] == 0:
            motivo = sin_lineas
        else:
            motivo = MOTIVO_EN_COLA
        return {
            **item,
            "motivo": motivo,
            "intentos": clave.attempts if clave is not None else None,
            "es_error": es_error,
        }

    return {"total": query.order_by(None).count(), "items": [fila(row) for row in filas]}


def alcance(db: Session, bono: SellInBonoMarca, limite: int) -> dict:
    alcanzadas = (
        db.query(
            SellInCompra.id,
            SellInCompra.bono_pedido_id,
            SellInCompra.monto_total,
            SellInCompra.moneda,
            PedidoCompra.numero,
            PedidoCompra.numero_factura,
            PedidoCompra.fecha_factura,
            Proveedor.nombre.label("proveedor_nombre"),
            func.coalesce(func.sum(SellInCompraItem.cantidad), 0).label("unidades"),
        )
        .outerjoin(PedidoCompra, PedidoCompra.id == SellInCompra.bono_pedido_id)
        .outerjoin(Proveedor, Proveedor.id == SellInCompra.proveedor_id)
        .outerjoin(SellInCompraItem, SellInCompraItem.compra_id == SellInCompra.id)
        .filter(SellInCompra.bono_id == bono.id, SellInCompra.origen == ORIGEN, SellInCompra.estado == "activa")
        .group_by(
            SellInCompra.id,
            SellInCompra.bono_pedido_id,
            SellInCompra.monto_total,
            SellInCompra.moneda,
            PedidoCompra.numero,
            PedidoCompra.numero_factura,
            PedidoCompra.fecha_factura,
            Proveedor.nombre,
        )
        # A purchase whose operation was deleted has no invoice date: last on every dialect.
        .order_by(PedidoCompra.fecha_factura.desc().nulls_last(), SellInCompra.id.desc())
    )

    recibidas = (
        db.query(
            PedidoCompraIngreso.pedido_id.label("pedido_id"),
            func.sum(PedidoCompraIngreso.cantidad_recibida).label("unidades"),
        )
        .join(ProductoERP, ProductoERP.item_id == PedidoCompraIngreso.item_id)
        .filter(_del_alcance(db, bono, PedidoCompraIngreso.item_id, PedidoCompraIngreso.pedido_id))
        .group_by(PedidoCompraIngreso.pedido_id)
        .subquery()
    )
    pendientes = (
        _pedidos_de_marca(db, recibidas)
        .filter(PedidoCompra.fecha_factura.is_(None))
        .order_by(PedidoCompra.created_at.desc(), PedidoCompra.id.desc())
    )

    # Never zero or negative: the snapshot holds whole units already net of credit notes, one row per
    # (pedido, item) with `CHECK (cantidad > 0)` (ck_pedido_compra_lineas_facturadas_cantidad_positiva), so a
    # fully credited line has no row and every brand operation that shows here sums at least one unit.
    facturadas = (
        db.query(
            PedidoCompraLineaFacturada.pedido_id.label("pedido_id"),
            func.sum(PedidoCompraLineaFacturada.cantidad).label("unidades"),
        )
        .join(ProductoERP, ProductoERP.item_id == PedidoCompraLineaFacturada.item_id)
        .filter(_del_alcance(db, bono, PedidoCompraLineaFacturada.item_id, PedidoCompraLineaFacturada.pedido_id))
        .group_by(PedidoCompraLineaFacturada.pedido_id)
        .subquery()
    )
    fuera = (
        _pedidos_de_marca(db, facturadas)
        .filter(
            PedidoCompra.fecha_factura.isnot(None),
            or_(PedidoCompra.fecha_factura < bono.fecha_desde, PedidoCompra.fecha_factura > bono.fecha_hasta),
        )
        .order_by(PedidoCompra.fecha_factura.desc(), PedidoCompra.id.desc())
    )

    return {
        "limite": limite,
        "alcanzadas": _grupo(
            alcanzadas,
            limite,
            lambda row: {
                "compra_id": row.id,
                "pedido_id": row.bono_pedido_id,
                "numero": row.numero,
                "proveedor_nombre": row.proveedor_nombre,
                "numero_factura": row.numero_factura,
                "fecha_factura": row.fecha_factura,
                "unidades": int(row.unidades),
                "monto": row.monto_total,
                "moneda": row.moneda,
            },
        ),
        "pendientes": _grupo(pendientes, limite, _pedido),
        "fuera_de_rango": _grupo(fuera, limite, _pedido),
        "sin_aplicar": _sin_aplicar(db, bono, facturadas, recibidas, limite),
    }
