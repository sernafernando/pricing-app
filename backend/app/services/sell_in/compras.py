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
The list and the detail report each line's consumed units (the sum of its
`sell_in_consumos`) and the units still left.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.pedido_compra import PedidoCompra
from app.models.producto import ProductoERP
from app.models.proveedor import Proveedor
from app.models.sell_in import SellInCompra, SellInCompraItem, SellInConsumo
from app.schemas.sell_in import SellInCompraCreate, SellInPreviewIn
from app.services.sell_in.split import CENT, UNIT_PRECISION, Line, SellInSplitError, preview, unit_discount


class SellInError(ValueError):
    """The request cannot be served as asked; the message is for the operator."""


class SellInYaAnulada(SellInError):
    """The purchase was already voided."""


def _moneda(value) -> str:
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
                Decimal(str(producto.costo)), _moneda(producto.moneda_costo), data.moneda, data.tipo_cambio
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


def _audit(
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
    """The supplier and purchase order, when given, must exist (a clear 422 instead of a foreign-key error)."""
    if data.proveedor_id is not None and db.get(Proveedor, data.proveedor_id) is None:
        raise SellInError(f"El proveedor {data.proveedor_id} no existe")
    if data.pedido_compra_id is not None and db.get(PedidoCompra, data.pedido_compra_id) is None:
        raise SellInError(f"El pedido de compra {data.pedido_compra_id} no existe")


def crear_compra(db: Session, data: SellInCompraCreate, usuario_id: int) -> SellInCompra:
    """Recompute the split, freeze each line's cost and save the purchase with its audit rows (one transaction).

    A reference that disappears between the checks and the write (a concurrent delete) surfaces as a
    foreign-key violation: the transaction is rolled back and it becomes a `SellInError` too.
    """
    if data.cuenta_desde == "ingreso" and data.fecha_ingreso is None:
        raise SellInError("Para contar desde el ingreso hace falta la fecha de ingreso")
    _validar_referencias(db, data)
    try:
        calculo = _calcular(db, data)
    except SellInSplitError as exc:
        raise SellInError(str(exc)) from exc

    try:
        compra = _guardar(db, data, calculo, usuario_id)
    except IntegrityError as exc:
        db.rollback()
        raise SellInError(
            "No se pudo guardar la compra: el proveedor, el pedido de compra o algún item dejó de existir"
        ) from exc
    db.refresh(compra)
    return compra


def _guardar(db: Session, data: SellInCompraCreate, calculo: _Calculo, usuario_id: int) -> SellInCompra:
    compra = SellInCompra(
        proveedor_id=data.proveedor_id,
        pedido_compra_id=data.pedido_compra_id,
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
    _audit(db, compra, items, TipoAccion.SELL_IN_COMPRA_CREADA, usuario_id)
    db.commit()
    return compra


def anular_compra(db: Session, compra_id: int, usuario_id: int, motivo: Optional[str]) -> Optional[SellInCompra]:
    """Void a purchase. None when it does not exist; `SellInYaAnulada` on a second call."""
    compra = db.query(SellInCompra).filter(SellInCompra.id == compra_id).with_for_update().first()
    if compra is None:
        return None
    if compra.estado == "anulada":
        raise SellInYaAnulada(f"La compra {compra_id} ya está anulada")
    compra.estado = "anulada"
    items = db.query(SellInCompraItem).filter(SellInCompraItem.compra_id == compra_id).order_by(SellInCompraItem.id)
    _audit(db, compra, list(items), TipoAccion.SELL_IN_COMPRA_ANULADA, usuario_id, motivo=motivo)
    db.commit()
    db.refresh(compra)
    return compra


def listar_compras(
    db: Session,
    *,
    item_id: Optional[int] = None,
    proveedor_id: Optional[int] = None,
    estado: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[SellInCompra], int]:
    """One page of purchases, newest purchase date first; the date range is inclusive on `fecha_compra`."""
    query = db.query(SellInCompra)
    if item_id is not None:
        query = query.filter(
            db.query(SellInCompraItem)
            .filter(SellInCompraItem.compra_id == SellInCompra.id, SellInCompraItem.item_id == item_id)
            .exists()
        )
    if proveedor_id is not None:
        query = query.filter(SellInCompra.proveedor_id == proveedor_id)
    if estado is not None:
        query = query.filter(SellInCompra.estado == estado)
    if fecha_desde is not None:
        query = query.filter(SellInCompra.fecha_compra >= fecha_desde)
    if fecha_hasta is not None:
        query = query.filter(SellInCompra.fecha_compra <= fecha_hasta)
    total = query.count()
    compras = (
        query.order_by(SellInCompra.fecha_compra.desc(), SellInCompra.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return compras, total


def serializar(db: Session, compras: list[SellInCompra]) -> list[dict]:
    """Purchases with their lines, products and consumed units (3 queries for the whole page)."""
    if not compras:
        return []
    ids = [c.id for c in compras]
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
