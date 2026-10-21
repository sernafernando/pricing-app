"""Sell-in purchases: preview, load, list, detail and void.

The preview and the load run the SAME code (`_calcular`): the server resolves
each line's base cost and splits the total with `split.preview`, so what the
operator saw is what gets saved. The client never sends the assigned amounts.

Base cost (`costo_base_unit`) is the product's plain cost, the same source the
Productos screen uses: `productos_erp.costo` in `productos_erp.moneda_costo`
(cost list 1, kept by `productos_sync`; see `convertir_a_pesos` in
`app/api/endpoints/productos_pricing.py`). It is converted into the purchase
currency with the purchase's own FX rate (`tipo_cambio`, ARS per USD) when the
currencies differ; there is no fallback to today's rate, so the frozen cost
always matches the rate the operator typed. The PPP cost is NOT used: it is
informational in Productos. A line can override the cost (`costo_base_unit`
in the body), already in the purchase currency.

A load freezes that cost on every line. A purchase is never edited nor deleted:
it can only be voided (`anulada`), once; the reason goes to the audit rows.
Loading and voiding recompute the allocation of the purchase's products in the
same transaction (`costing.get_costing()`): a load is consumed by the sales
already made since it counts, a void releases its units to later purchases.
The list and the detail report each line's consumed units (the sum of its
`sell_in_consumos`) and the units still left, the supplier's name and whether
the purchase applies (`aplica_condicion`, the single rule for it). The list and
its summary (`resumir_compras`) share the same filters (`FiltrosCompras`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional, Tuple

from sqlalchemy import and_, case, func, literal, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.pedido_compra import PedidoCompra
from app.models.producto import ProductoERP
from app.models.proveedor import Proveedor
from app.models.sell_in import SellInCompra, SellInCompraItem, SellInCompraPedido, SellInConsumo
from app.schemas.sell_in import SellInCompraCreate, SellInPreviewIn
from app.services.sell_in.costing import get_costing
from app.services.sell_in.split import CENT, UNIT_PRECISION, Line, SellInSplitError, preview, unit_discount


class SellInError(ValueError):
    """The request cannot be served as asked; the message is for the operator."""


class SellInYaAnulada(SellInError):
    """The purchase was already voided."""


def moneda(value) -> str:
    """An ORM or enum currency as its code; ARS when empty."""
    return getattr(value, "value", value) or "ARS"


def costo_en_moneda(costo: Decimal, moneda_costo: str, moneda_compra: str, tipo_cambio: Optional[Decimal]) -> Decimal:
    """Convert a unit cost into the purchase currency with the purchase's FX rate (ARS per USD)."""
    if moneda_costo == moneda_compra:
        converted = costo
    elif tipo_cambio is None:
        raise SellInError(f"Falta el tipo de cambio para pasar un costo en {moneda_costo} a {moneda_compra}")
    elif moneda_compra == "ARS":
        converted = costo * tipo_cambio
    else:
        converted = costo / tipo_cambio
    return converted.quantize(UNIT_PRECISION, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class _Calculo:
    lineas: list[dict]
    totales: dict


def _calcular(db: Session, data: SellInPreviewIn) -> _Calculo:
    if data.tipo_cambio is not None and data.tipo_cambio <= 0:
        raise SellInError("El tipo de cambio debe ser positivo")
    if data.moneda == "USD" and data.tipo_cambio is None:
        raise SellInError("Una compra en USD necesita el tipo de cambio")

    item_ids = [linea.item_id for linea in data.lineas]
    productos = (
        {p.item_id: p for p in db.query(ProductoERP).filter(ProductoERP.item_id.in_(item_ids))} if item_ids else {}
    )

    lines: list[Line] = []
    for linea in data.lineas:
        producto = productos.get(linea.item_id)
        if producto is None:
            raise SellInError(f"El item {linea.item_id} no existe")
        if linea.costo_base_unit is not None:
            if linea.costo_base_unit < 0:
                raise SellInError(f"El costo base no puede ser negativo (item {linea.item_id})")
            # Same precision as a converted product cost, so the preview shows exactly what gets stored.
            costo = linea.costo_base_unit.quantize(UNIT_PRECISION, rounding=ROUND_HALF_UP)
        elif producto.costo is None:
            raise SellInError(f"El item {linea.item_id} no tiene costo cargado: indicá el costo base a mano")
        else:
            costo = costo_en_moneda(
                Decimal(str(producto.costo)), moneda(producto.moneda_costo), data.moneda, data.tipo_cambio
            )
        lines.append(Line(linea.item_id, linea.cantidad, costo, linea.monto_manual))

    filas = preview(data.formula, data.monto_total, lines)
    lineas = [
        {
            "item_id": fila.item_id,
            "codigo": productos[fila.item_id].codigo,
            "descripcion": productos[fila.item_id].descripcion,
            "cantidad": fila.cantidad,
            "costo_base_unit": fila.costo_base_unit,
            "monto_asignado": fila.monto_asignado,
            "descuento_unit": fila.descuento_unit,
            "costo_con_sell_in_unit": fila.costo_con_sell_in_unit,
            "porcentaje": fila.porcentaje,
        }
        for fila in filas
    ]
    costo_base_total = sum((f.costo_base_unit * f.cantidad for f in filas), Decimal("0"))
    asignado_total = sum((f.monto_asignado for f in filas), Decimal("0"))
    porcentaje = None
    if costo_base_total > 0:
        porcentaje = (asignado_total * 100 / costo_base_total).quantize(CENT, rounding=ROUND_HALF_UP)
    totales = {
        "cantidad": sum(f.cantidad for f in filas),
        "costo_base_total": costo_base_total,
        "monto_asignado_total": asignado_total,
        "costo_con_sell_in_total": costo_base_total - asignado_total,
        "porcentaje": porcentaje,
    }
    return _Calculo(lineas, totales)


def calcular_preview(db: Session, data: SellInPreviewIn) -> dict:
    """The split the purchase would get, without writing anything."""
    try:
        calculo = _calcular(db, data)
    except SellInSplitError as exc:
        raise SellInError(str(exc)) from exc
    return {
        "moneda": data.moneda,
        "formula": data.formula,
        "monto_total": data.monto_total,
        "lineas": calculo.lineas,
        "totales": calculo.totales,
    }


def audit(
    db: Session,
    compra: SellInCompra,
    items: list[SellInCompraItem],
    tipo: TipoAccion,
    usuario_id: int,
    motivo: Optional[str] = None,
) -> None:
    """One audit row per line; `motivo` (the void's reason, if any) goes to `comentario`."""
    fecha = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, like the column's default
    for item in items:
        valores = {
            "compra_id": compra.id,
            "cantidad": item.cantidad,
            "costo_base_unit": str(item.costo_base_unit),
            "monto_asignado": str(item.monto_asignado),
            "moneda": compra.moneda,
            "estado": compra.estado,
        }
        db.add(
            Auditoria(
                item_id=item.item_id,
                usuario_id=usuario_id,
                tipo_accion=tipo,
                valores_anteriores=None,
                valores_nuevos=valores,
                es_masivo=0,
                comentario=motivo,
                fecha=fecha,
            )
        )


def _validar_referencias(db: Session, data: SellInCompraCreate) -> None:
    """The supplier, when given, must exist (a clear 422 instead of a foreign-key error)."""
    if data.proveedor_id is not None and db.get(Proveedor, data.proveedor_id) is None:
        raise SellInError(f"El proveedor {data.proveedor_id} no existe")


def ids_pedidos(data: SellInCompraCreate) -> list[int]:
    """The purchase's operations: `pedido_compra_ids` deduplicated in order, the legacy single
    `pedido_compra_id` read as a one-element list. When both come, the single one must be in the list."""
    ids = list(dict.fromkeys(data.pedido_compra_ids))
    legado = data.pedido_compra_id
    if legado is not None and not ids:
        return [legado]
    if legado is not None and legado not in ids:
        raise SellInError(f"El pedido de compra {legado} no figura entre las operaciones indicadas")
    return ids


@dataclass(frozen=True)
class Operaciones:
    """Compras operations that may feed one sell in: they exist and share supplier and currency."""

    pedidos: list[PedidoCompra]
    proveedor_id: int
    moneda: str


def operaciones(db: Session, ids: list[int]) -> Optional[Operaciones]:
    """Loads and checks the operations (`pedidos_compra`); None when there are none."""
    if not ids:
        return None
    pedidos = {p.id: p for p in db.query(PedidoCompra).filter(PedidoCompra.id.in_(ids))}
    faltante = next((i for i in ids if i not in pedidos), None)
    if faltante is not None:
        raise SellInError(f"El pedido de compra {faltante} no existe")
    ordenados = [pedidos[i] for i in ids]
    if len({p.proveedor_id for p in ordenados}) > 1:
        raise SellInError("Las operaciones son de proveedores distintos: un sell in es de un solo proveedor")
    monedas = sorted({p.moneda for p in ordenados})
    if len(monedas) > 1:
        raise SellInError(f"Las operaciones están en monedas distintas ({' y '.join(monedas)}): no se pueden combinar")
    return Operaciones(ordenados, ordenados[0].proveedor_id, monedas[0])


def _validar_contra_operaciones(data: SellInCompraCreate, ops: Operaciones) -> None:
    """The purchase's own supplier, when given, must be the operations' one. Its currency is its
    own: a credit in ARS on USD operations is fine, costs convert at the purchase's `tipo_cambio`."""
    if data.proveedor_id is not None and data.proveedor_id != ops.proveedor_id:
        raise SellInError("El proveedor de la compra no coincide con el de las operaciones")


def crear_compra(db: Session, data: SellInCompraCreate, usuario_id: int) -> SellInCompra:
    """Recompute the split, freeze each line's cost and save the purchase with its audit rows (one transaction).

    A reference that disappears between the checks and the write (a concurrent delete) surfaces as a
    foreign-key violation: the transaction is rolled back and it becomes a `SellInError` too. Any
    failure of the recompute that follows (an `IntegrityError` included) is rolled back and raised
    as itself: it says nothing about the purchase's references.
    """
    if data.cuenta_desde == "ingreso" and data.fecha_ingreso is None:
        raise SellInError("Para contar desde el ingreso hace falta la fecha de ingreso")
    _validar_referencias(db, data)
    ids = ids_pedidos(data)
    ops = operaciones(db, ids)
    if ops is not None:
        _validar_contra_operaciones(data, ops)
    try:
        calculo = _calcular(db, data)
    except SellInSplitError as exc:
        raise SellInError(str(exc)) from exc

    try:
        compra, items = _guardar(db, data, calculo, usuario_id, ids, ops)
    except IntegrityError as exc:
        db.rollback()
        raise SellInError(
            "No se pudo guardar la compra: el proveedor, el pedido de compra o algún item dejó de existir"
        ) from exc
    except Exception:
        db.rollback()  # never leave the caller's session aborted
        raise
    try:
        # The sales already made since the purchase counts consume it in the same transaction.
        get_costing().recompute(db, [item.item_id for item in items], isolate_failures=False)
        db.commit()
    except Exception:
        db.rollback()  # a failed recompute takes the purchase with it; never leave the session aborted
        raise
    db.refresh(compra)
    return compra


def _guardar(
    db: Session,
    data: SellInCompraCreate,
    calculo: _Calculo,
    usuario_id: int,
    ids: list[int],
    ops: Optional[Operaciones],
) -> Tuple[SellInCompra, List[SellInCompraItem]]:
    """Writes the purchase, its operation links, lines and audit rows (flushed, not committed): every
    `IntegrityError` it raises is about the purchase's own references. Without a supplier of its own the
    purchase takes the operations' one; the legacy `pedido_compra_id` column keeps the single id sent,
    else the first operation (until the column is dropped)."""
    compra = SellInCompra(
        proveedor_id=data.proveedor_id if data.proveedor_id is not None else (ops.proveedor_id if ops else None),
        pedido_compra_id=data.pedido_compra_id if data.pedido_compra_id is not None else (ids[0] if ids else None),
        fecha_compra=data.fecha_compra,
        fecha_ingreso=data.fecha_ingreso,
        cuenta_desde=data.cuenta_desde,
        moneda=data.moneda,
        monto_total=data.monto_total,
        tipo_cambio=data.tipo_cambio,
        formula=data.formula,
        estado="activa",
        descripcion=data.descripcion,
        usuario_id=usuario_id,
    )
    db.add(compra)
    db.flush()
    _sincronizar_pedidos(db, compra, ids)
    items = [
        SellInCompraItem(
            compra_id=compra.id,
            item_id=linea["item_id"],
            cantidad=linea["cantidad"],
            costo_base_unit=linea["costo_base_unit"],
            monto_asignado=linea["monto_asignado"],
        )
        for linea in calculo.lineas
    ]
    db.add_all(items)
    db.flush()
    audit(db, compra, items, TipoAccion.SELL_IN_COMPRA_CREADA, usuario_id)
    db.flush()  # the audit rows too, so their errors are raised here and not by the recompute's autoflush
    return compra, items


def _sincronizar_pedidos(db: Session, compra: SellInCompra, ids: list[int]) -> None:
    """Makes the purchase's link rows (`SellInCompraPedido`) match `ids`: missing ones added, others
    removed. Flushes, so a repeat call sees its own rows even with autoflush off."""
    deseados = set(ids)
    existentes = db.query(SellInCompraPedido).filter(SellInCompraPedido.compra_id == compra.id).all()
    for link in existentes:
        if link.pedido_compra_id not in deseados:
            db.delete(link)
    tenidos = {link.pedido_compra_id for link in existentes}
    for pedido_id in dict.fromkeys(ids):
        if pedido_id not in tenidos:
            db.add(SellInCompraPedido(compra_id=compra.id, pedido_compra_id=pedido_id))
    db.flush()


def anular_compra(db: Session, compra_id: int, usuario_id: int, motivo: Optional[str]) -> Optional[SellInCompra]:
    """Void a purchase. None when it does not exist; `SellInYaAnulada` on a second call."""
    compra = db.query(SellInCompra).filter(SellInCompra.id == compra_id).with_for_update().first()
    if compra is None:
        return None
    if compra.estado == "anulada":
        raise SellInYaAnulada(f"La compra {compra_id} ya está anulada")
    compra.estado = "anulada"
    items = list(
        db.query(SellInCompraItem).filter(SellInCompraItem.compra_id == compra_id).order_by(SellInCompraItem.id)
    )
    audit(db, compra, items, TipoAccion.SELL_IN_COMPRA_ANULADA, usuario_id, motivo=motivo)
    db.flush()
    # Its units are released in the same transaction: later purchases take those sales over.
    try:
        get_costing().recompute(db, [item.item_id for item in items], isolate_failures=False)
        db.commit()
    except Exception:
        db.rollback()  # the purchase stays activa and unaudited; never leave the session aborted
        raise
    db.refresh(compra)
    return compra


def aplica_condicion():
    """THE rule for "this sell in applies", as a SQL boolean over `SellInCompra`.

    A purchase applies while it is not voided (`estado = 'activa'`) AND it
    still has units left: some line whose `sell_in_consumos` add up to less
    than its `cantidad`. The `aplica` filter, the per-row `aplica` flag and the
    summary buckets all follow it. Never restate this condition elsewhere.
    """
    consumidas = (
        select(func.coalesce(func.sum(SellInConsumo.unidades), 0))
        .where(SellInConsumo.compra_item_id == SellInCompraItem.id)
        .correlate(SellInCompraItem)
        .scalar_subquery()
    )
    con_unidades = (
        select(SellInCompraItem.id)
        .where(SellInCompraItem.compra_id == SellInCompra.id, SellInCompraItem.cantidad > consumidas)
        .correlate(SellInCompra)
        .exists()
    )
    return and_(SellInCompra.estado == "activa", con_unidades)


@dataclass(frozen=True)
class FiltrosCompras:
    """The filters shared by the list and its summary. Every field is optional (None = no filter)."""

    item_id: Optional[int] = None
    proveedor_id: Optional[int] = None
    estado: Optional[str] = None
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    aplica: Optional[str] = None  # "si" | "no" | "todas"
    q: Optional[str] = None
    marcas: Optional[list[str]] = None
    moneda: Optional[str] = None


def _items_que_cumplen(db: Session, *condiciones):
    """EXISTS a line of this purchase whose product meets `condiciones`."""
    return (
        db.query(SellInCompraItem)
        .join(ProductoERP, ProductoERP.item_id == SellInCompraItem.item_id)
        .filter(SellInCompraItem.compra_id == SellInCompra.id, *condiciones)
        .exists()
    )


_LIKE_ESCAPE = "\\"


def contiene(columna, q: str):
    """`columna` contains `q`, ignoring case, with the folding done by the DATABASE on both sides.

    SQLAlchemy's `ilike` is `ILIKE` on Postgres and `lower(x) LIKE lower(y)` elsewhere, so the query
    is never lowercased in Python (which folds some letters, like "İ", differently than Postgres).
    LIKE wildcards in `q` are literal. Not accent-insensitive: that needs the `unaccent` extension,
    which production does not have installed.
    """
    escapado = q.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", "\\%").replace("_", "\\_")
    return func.coalesce(columna, "").ilike(f"%{escapado}%", escape=_LIKE_ESCAPE)


def _texto(db: Session, q: str):
    """Case-insensitive substring over supplier name, the lines' product code or description,
    the purchase's own reference text (`descripcion`) and its purchase orders' numbers, through
    `SellInCompraPedido` or the `pedido_compra_id` column (a writer that skips the link sync still matches)."""
    return or_(
        contiene(SellInCompra.descripcion, q),
        db.query(Proveedor).filter(Proveedor.id == SellInCompra.proveedor_id, contiene(Proveedor.nombre, q)).exists(),
        db.query(SellInCompraPedido)
        .join(PedidoCompra, PedidoCompra.id == SellInCompraPedido.pedido_compra_id)
        .filter(SellInCompraPedido.compra_id == SellInCompra.id, contiene(PedidoCompra.numero, q))
        .exists(),
        db.query(PedidoCompra)
        .filter(PedidoCompra.id == SellInCompra.pedido_compra_id, contiene(PedidoCompra.numero, q))
        .exists(),
        _items_que_cumplen(db, or_(contiene(ProductoERP.codigo, q), contiene(ProductoERP.descripcion, q))),
    )


def _filtrada(db: Session, filtros: FiltrosCompras, *, con_aplica: bool = True):
    """The purchases matching `filtros`; `con_aplica=False` leaves the `aplica` filter out (summary buckets)."""
    query = db.query(SellInCompra)
    if filtros.item_id is not None:
        query = query.filter(
            db.query(SellInCompraItem)
            .filter(SellInCompraItem.compra_id == SellInCompra.id, SellInCompraItem.item_id == filtros.item_id)
            .exists()
        )
    if filtros.proveedor_id is not None:
        query = query.filter(SellInCompra.proveedor_id == filtros.proveedor_id)
    if filtros.estado is not None:
        query = query.filter(SellInCompra.estado == filtros.estado)
    if filtros.fecha_desde is not None:
        query = query.filter(SellInCompra.fecha_compra >= filtros.fecha_desde)
    if filtros.fecha_hasta is not None:
        query = query.filter(SellInCompra.fecha_compra <= filtros.fecha_hasta)
    if filtros.moneda is not None:
        query = query.filter(SellInCompra.moneda == filtros.moneda)
    q = (filtros.q or "").strip()
    if q:
        query = query.filter(_texto(db, q))
    if filtros.marcas:
        query = query.filter(_items_que_cumplen(db, ProductoERP.marca.in_(filtros.marcas)))
    if con_aplica and filtros.aplica == "si":
        query = query.filter(aplica_condicion())
    elif con_aplica and filtros.aplica == "no":
        query = query.filter(not_(aplica_condicion()))
    return query


def listar_compras(
    db: Session, filtros: FiltrosCompras, *, page: int = 1, page_size: int = 50
) -> tuple[list[SellInCompra], int]:
    """One page of purchases, newest purchase date first; the date range is inclusive on `fecha_compra`."""
    query = _filtrada(db, filtros)
    total = query.count()
    compras = (
        query.order_by(SellInCompra.fecha_compra.desc(), SellInCompra.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return compras, total


def resumir_compras(db: Session, filtros: FiltrosCompras) -> dict:
    """Exact aggregates over EVERY matching purchase (not a page), in two set-based queries.

    - `conteo`: purchases per `aplica` bucket. It ignores the `aplica` filter itself, so
      the three buckets stay visible whichever one is selected (`si + no = todas`).
    - `monto_total`: the sell-in amount per currency (ARS, USD) of the matching purchases.
    - `unidades_total`: units covered by the lines of the matching purchases.
    """
    aplica = aplica_condicion()
    if filtros.aplica == "si":
        elegida = aplica
    elif filtros.aplica == "no":
        elegida = not_(aplica)
    else:
        elegida = literal(True)
    base = (
        _filtrada(db, filtros, con_aplica=False)
        .with_entities(
            SellInCompra.id.label("id"),
            SellInCompra.moneda.label("moneda"),
            SellInCompra.monto_total.label("monto_total"),
            case((aplica, 1), else_=0).label("aplica"),
            case((elegida, 1), else_=0).label("elegida"),
        )
        .subquery()
    )

    def _monto(moneda: str):
        return func.coalesce(
            func.sum(case(((base.c.elegida == 1) & (base.c.moneda == moneda), base.c.monto_total), else_=0)), 0
        )

    todas, si, ars, usd = db.query(
        func.count(base.c.id), func.coalesce(func.sum(base.c.aplica), 0), _monto("ARS"), _monto("USD")
    ).one()
    unidades = (
        db.query(func.coalesce(func.sum(SellInCompraItem.cantidad), 0))
        .join(base, base.c.id == SellInCompraItem.compra_id)
        .filter(base.c.elegida == 1)
        .scalar()
    )
    return {
        "conteo": {"si": int(si), "no": int(todas) - int(si), "todas": int(todas)},
        "monto_total": {"ARS": Decimal(str(ars)), "USD": Decimal(str(usd))},
        "unidades_total": int(unidades),
    }


def serializar(db: Session, compras: list[SellInCompra]) -> list[dict]:
    """Purchases with their lines, products, consumed units, supplier name, operations and `aplica`
    (5 queries per page)."""
    if not compras:
        return []
    ids = [c.id for c in compras]
    cabeceras = {
        compra_id: (bool(aplica), nombre)
        for compra_id, aplica, nombre in db.query(SellInCompra.id, aplica_condicion(), Proveedor.nombre)
        .outerjoin(Proveedor, Proveedor.id == SellInCompra.proveedor_id)
        .filter(SellInCompra.id.in_(ids))
    }
    items = (
        db.query(SellInCompraItem)
        .filter(SellInCompraItem.compra_id.in_(ids))
        .order_by(SellInCompraItem.compra_id, SellInCompraItem.id)
        .all()
    )
    item_ids = {i.item_id for i in items}
    productos = {p.item_id: p for p in db.query(ProductoERP).filter(ProductoERP.item_id.in_(item_ids))} if items else {}
    consumidas = (
        dict(
            db.query(SellInConsumo.compra_item_id, func.coalesce(func.sum(SellInConsumo.unidades), 0))
            .filter(SellInConsumo.compra_item_id.in_([i.id for i in items]))
            .group_by(SellInConsumo.compra_item_id)
            .all()
        )
        if items
        else {}
    )

    # The column too, so a writer that skips the link sync still shows its operation.
    pedidos: dict[int, set[int]] = {c.id: {c.pedido_compra_id} - {None} for c in compras}
    for compra_id, pedido_id in db.query(SellInCompraPedido.compra_id, SellInCompraPedido.pedido_compra_id).filter(
        SellInCompraPedido.compra_id.in_(ids)
    ):
        pedidos[compra_id].add(pedido_id)

    por_compra: dict[int, list[dict]] = {c.id: [] for c in compras}
    for item in items:
        costo = Decimal(item.costo_base_unit)
        monto = Decimal(item.monto_asignado)
        descuento = unit_discount(monto, item.cantidad)
        usadas = int(consumidas.get(item.id, 0))
        producto = productos.get(item.item_id)
        por_compra[item.compra_id].append(
            {
                "id": item.id,
                "item_id": item.item_id,
                "codigo": producto.codigo if producto else None,
                "descripcion": producto.descripcion if producto else None,
                "cantidad": item.cantidad,
                "costo_base_unit": costo,
                "monto_asignado": monto,
                "descuento_unit": descuento,
                "costo_con_sell_in_unit": (costo - descuento).quantize(UNIT_PRECISION),
                "porcentaje": (descuento * 100 / costo).quantize(CENT, rounding=ROUND_HALF_UP) if costo > 0 else None,
                "unidades_consumidas": usadas,
                "unidades_restantes": item.cantidad - usadas,
            }
        )

    filas = []
    for compra in compras:
        lineas = por_compra[compra.id]
        total = sum(linea["cantidad"] for linea in lineas)
        usadas = sum(linea["unidades_consumidas"] for linea in lineas)
        filas.append(
            {
                **{col: getattr(compra, col) for col in _COLUMNAS_COMPRA},
                "aplica": cabeceras[compra.id][0],
                "proveedor_nombre": cabeceras[compra.id][1],
                "pedido_compra_ids": sorted(pedidos[compra.id]),
                "unidades_total": total,
                "unidades_consumidas": usadas,
                "unidades_restantes": total - usadas,
                "items": lineas,
            }
        )
    return filas


_COLUMNAS_COMPRA = (
    "id",
    "proveedor_id",
    "pedido_compra_id",
    "fecha_compra",
    "fecha_ingreso",
    "cuenta_desde",
    "moneda",
    "monto_total",
    "tipo_cambio",
    "formula",
    "estado",
    "descripcion",
    "usuario_id",
    "created_at",
    "updated_at",
)
