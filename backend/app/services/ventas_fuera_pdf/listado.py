"""The PDF operations list (vpf-operaciones S2, S3): one row per document with its lines, filters, totals and the
"sin producto" summary by cause, read from the stored lines (their `item_id`, the manual fixes already applied).

Money rules = the Métricas board's (`app.services.ml_daily_metrics.fuera`): a line counts in the cost, Total Gauss
and markup only when it is ARS and has a cost (precio_costo != 0); cost = Costo D (precio_costo x COSTO_D_FACTOR,
default) or precio_costo (`costo='costo'`); Total Gauss = precio - cost; markup (%) = Total Gauss / cost x 100; the
sale (`venta`) is the ARS lines' precio (without VAT); credit notes are negative as stored. `markup` is a percentage
rounded to 2 decimals. Total Gauss and markup are None for a caller without `ventas_fuera.ver_ganancia`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import String, and_, case, cast, exists, func, literal, or_, select
from sqlalchemy.orm import Session

from app.models.producto import ProductoERP
from app.models.tb_item import TBItem
from app.models.usuario import Usuario
from app.models.venta_fuera_pdf import (
    VentaFueraLineaOverride,
    VentaFueraOperacion,
    VentaFueraOperacionLinea,
)
from app.services.ml_daily_metrics.fuera import COSTO_D_FACTOR, _vendedores_guardados
from app.services.ventas_fuera_pdf.carga import CONDICION_CHEQUE
from app.services.ventas_fuera_pdf.resolucion import causa_sin_producto

OP = VentaFueraOperacion.__table__
LN = VentaFueraOperacionLinea.__table__
COSTOS = ("costo_d", "costo")
ORDENES = ("fecha_desc", "fecha_asc", "importe_desc", "markup_asc")
CERO = Decimal("0")


@dataclass(frozen=True)
class Filtros:
    desde: date
    hasta: date
    empresas: tuple[str, ...] = ()
    vendedores: tuple[str, ...] = ()
    q: Optional[str] = None
    tipo: Optional[str] = None
    sin_producto: bool = False
    revisar: bool = False
    costo: str = "costo_d"
    page: int = 1
    page_size: int = 50
    sort: str = "fecha_desc"


@dataclass
class Listado:
    total: int
    page: int
    page_size: int
    totales: dict
    facets: dict
    operaciones: list[dict] = field(default_factory=list)


def _factor(costo: str) -> Decimal:
    return COSTO_D_FACTOR if costo == "costo_d" else Decimal("1")


def _num(valor: Any) -> Optional[float]:
    return None if valor is None else float(round(Decimal(valor), 2))


def _markup(total_gauss: Any, costo: Any) -> Optional[float]:
    if total_gauss is None or not costo:
        return None
    return float(round(Decimal(total_gauss) / Decimal(costo) * 100, 2))


def _agregados(costo: str) -> Any:
    """Per document: lines, units, sale, cost, Total Gauss, sin producto lines and sale, lines to review."""
    ars = LN.c.moneda == "ARS"
    counted = and_(ars, LN.c.precio_costo != 0)
    cost = LN.c.precio_costo * literal(_factor(costo))
    sin_producto = LN.c.item_id.is_(None)
    return (
        select(
            LN.c.operacion_id,
            func.count().label("lineas"),
            func.sum(LN.c.cantidad).label("unidades"),
            func.sum(case((ars, LN.c.precio), else_=0)).label("venta"),
            func.sum(case((counted, cost), else_=0)).label("costo"),
            func.sum(case((counted, LN.c.precio - cost), else_=0)).label("total_gauss"),
            func.count().filter(sin_producto).label("sin_producto_lineas"),
            func.sum(case((sin_producto, LN.c.precio), else_=0)).label("sin_producto_venta"),
            func.count().filter(LN.c.override_estado == "revisar").label("revisar_lineas"),
        )
        .group_by(LN.c.operacion_id)
        .subquery("vpf_agregados")
    )


def _condiciones(f: Filtros, agg: Any, *, sin_empresas: bool = False, sin_vendedores: bool = False) -> list:
    condiciones = [OP.c.fecha.between(f.desde, f.hasta)]
    if f.empresas and not sin_empresas:
        condiciones.append(OP.c.empresa.in_(f.empresas))
    if f.vendedores and not sin_vendedores:
        condiciones.append(OP.c.vendedor.in_(_vendedores_guardados(f.vendedores)))
    if f.tipo:
        condiciones.append(OP.c.tipo == f.tipo)
    if f.q and f.q.strip():
        patron = f"%{f.q.strip()}%"
        en_lineas = exists().where(
            LN.c.operacion_id == OP.c.id, or_(LN.c.articulo.ilike(patron), LN.c.codigo.ilike(patron))
        )
        condiciones.append(or_(OP.c.cliente.ilike(patron), cast(OP.c.numero, String).ilike(patron), en_lineas))
    if f.sin_producto:
        condiciones.append(func.coalesce(agg.c.sin_producto_lineas, 0) > 0)
    if f.revisar:
        condiciones.append(func.coalesce(agg.c.revisar_lineas, 0) > 0)
    return condiciones


def _orden(f: Filtros, agg: Any) -> list:
    if f.sort == "fecha_asc":
        return [OP.c.fecha.asc(), OP.c.id.asc()]
    if f.sort == "importe_desc":
        return [OP.c.importe.desc(), OP.c.id.desc()]
    if f.sort == "markup_asc":
        markup = agg.c.total_gauss / func.nullif(agg.c.costo, 0)
        return [markup.asc().nulls_last(), OP.c.id.asc()]
    return [OP.c.fecha.desc(), OP.c.id.desc()]


def listar(db: Session, f: Filtros, ver_ganancia: bool) -> Listado:
    """A page of documents with their lines, the filtered totals and the empresa / vendedor options (each narrowed by
    the other filter, never by its own, like the board's chips)."""
    agg = _agregados(f.costo)
    base = OP.outerjoin(agg, agg.c.operacion_id == OP.c.id)
    condiciones = _condiciones(f, agg)
    totales = db.execute(
        select(
            func.count().label("documentos"),
            func.coalesce(func.sum(agg.c.lineas), 0),
            func.coalesce(func.sum(agg.c.unidades), 0),
            func.coalesce(func.sum(agg.c.venta), 0),
            func.coalesce(func.sum(agg.c.costo), 0),
            func.coalesce(func.sum(agg.c.total_gauss), 0),
            func.coalesce(func.sum(agg.c.sin_producto_lineas), 0),
            func.coalesce(func.sum(agg.c.sin_producto_venta), 0),
            func.coalesce(func.sum(agg.c.revisar_lineas), 0),
        )
        .select_from(base)
        .where(*condiciones)
    ).one()
    documentos, lineas, unidades, venta, costo, total_gauss, sp_lineas, sp_venta, revisar = totales
    filas = (
        db.execute(
            select(OP, *(c for c in agg.c if c.name != "operacion_id"))
            .select_from(base)
            .where(*condiciones)
            .order_by(*_orden(f, agg))
            .limit(f.page_size)
            .offset((f.page - 1) * f.page_size)
        )
        .mappings()
        .all()
    )
    lineas_por_op = _lineas(db, [fila["id"] for fila in filas])
    detalle = _detalle(db, [ln for lns in lineas_por_op.values() for ln in lns])
    operaciones = []
    for fila in filas:
        operaciones.append(
            {
                "id": fila["id"],
                "fecha": fila["fecha"],
                "empresa": fila["empresa"],
                "vendedor": fila["vendedor"],
                "cliente": fila["cliente"],
                "tipo": fila["tipo"],
                "letra": fila["letra"],
                "punto_venta": fila["punto_venta"],
                "numero": fila["numero"],
                "condicion_venta": fila["condicion_venta"],
                "cheque": (fila["condicion_venta"] or "").upper().startswith(CONDICION_CHEQUE),
                "recargo_financiero": _num(fila["recargo_financiero"]),
                "importe": _num(fila["importe"]),
                "venta": _num(fila["venta"] or CERO),
                "costo": _num(fila["costo"] or CERO),
                "total_gauss": _num(fila["total_gauss"] or CERO) if ver_ganancia else None,
                "markup": _markup(fila["total_gauss"], fila["costo"]) if ver_ganancia else None,
                "sin_producto_lineas": fila["sin_producto_lineas"] or 0,
                "revisar_lineas": fila["revisar_lineas"] or 0,
                "lineas": [linea_dict(ln, detalle, f.costo, ver_ganancia) for ln in lineas_por_op.get(fila["id"], [])],
            }
        )
    return Listado(
        total=documentos,
        page=f.page,
        page_size=f.page_size,
        totales={
            "documentos": documentos,
            "lineas": int(lineas),
            "unidades": _num(unidades),
            "venta": _num(venta),
            "costo": _num(costo),
            "total_gauss": _num(total_gauss) if ver_ganancia else None,
            "markup": _markup(total_gauss, costo) if ver_ganancia else None,
            "sin_producto_lineas": int(sp_lineas),
            "sin_producto_venta": _num(sp_venta),
            "revisar_lineas": int(revisar),
        },
        facets=_facets(db, f, agg),
        operaciones=operaciones,
    )


def _facets(db: Session, f: Filtros, agg: Any) -> dict:
    def opciones(columna: Any, **sin: bool) -> list[str]:
        consulta = (
            select(columna)
            .select_from(OP.outerjoin(agg, agg.c.operacion_id == OP.c.id))
            .where(*_condiciones(f, agg, **sin))
            .distinct()
            .order_by(columna)
        )
        return list(db.execute(consulta).scalars())

    return {
        "empresas": opciones(OP.c.empresa, sin_empresas=True),
        "vendedores": opciones(OP.c.vendedor, sin_vendedores=True),
    }


def _lineas(db: Session, operacion_ids: list[int]) -> dict[int, list[VentaFueraOperacionLinea]]:
    if not operacion_ids:
        return {}
    por_op: dict[int, list[VentaFueraOperacionLinea]] = {}
    for ln in db.execute(
        select(VentaFueraOperacionLinea)
        .where(VentaFueraOperacionLinea.operacion_id.in_(operacion_ids))
        .order_by(VentaFueraOperacionLinea.operacion_id, VentaFueraOperacionLinea.renglon)
    ).scalars():
        por_op.setdefault(ln.operacion_id, []).append(ln)
    return por_op


@dataclass
class _Detalle:
    productos: dict[int, tuple]
    overrides: dict[tuple, tuple]


def _detalle(db: Session, lineas: list[VentaFueraOperacionLinea]) -> _Detalle:
    """The products (description, brand, category) and the manual fixes (with their user's name) of `lineas`."""
    item_ids = {ln.item_id for ln in lineas if ln.item_id is not None}
    productos: dict[int, tuple] = {}
    if item_ids:
        productos = {
            item_id: (descripcion, marca, categoria)
            for item_id, descripcion, marca, categoria in db.execute(
                select(ProductoERP.item_id, ProductoERP.descripcion, ProductoERP.marca, ProductoERP.categoria).where(
                    ProductoERP.item_id.in_(item_ids)
                )
            ).all()
        }
        faltan = item_ids - set(productos)
        if faltan:
            productos.update(
                (item_id, (descripcion, None, None))
                for item_id, descripcion in db.execute(
                    select(TBItem.item_id, func.min(TBItem.item_desc))
                    .where(TBItem.item_id.in_(faltan))
                    .group_by(TBItem.item_id)
                ).all()
            )
    operacion_ids = {ln.operacion_id for ln in lineas}
    overrides: dict[tuple, tuple] = {}
    if operacion_ids:
        O = VentaFueraLineaOverride
        filas = db.execute(
            select(OP.c.id, O, Usuario.nombre)
            .join(
                O,
                and_(
                    O.empresa == OP.c.empresa,
                    O.tipo == OP.c.tipo,
                    O.letra == OP.c.letra,
                    O.punto_venta == OP.c.punto_venta,
                    O.numero == OP.c.numero,
                ),
            )
            .outerjoin(Usuario, Usuario.id == O.usuario_id)
            .where(OP.c.id.in_(operacion_ids))
        ).all()
        overrides = {(op_id, o.renglon): (o, nombre) for op_id, o, nombre in filas}
    return _Detalle(productos, overrides)


def linea_dict(ln: VentaFueraOperacionLinea, detalle: _Detalle, costo: str, ver_ganancia: bool) -> dict:
    """A line as the list shows it."""
    counted = ln.moneda == "ARS" and Decimal(ln.precio_costo) != 0
    costo_linea = Decimal(ln.precio_costo) * _factor(costo)
    tg = Decimal(ln.precio) - costo_linea if counted and ver_ganancia else None
    descripcion, marca, categoria = detalle.productos.get(ln.item_id, (None, None, None))
    override = detalle.overrides.get((ln.operacion_id, ln.renglon))
    sin_producto = ln.item_id is None
    return {
        "id": ln.id,
        "renglon": ln.renglon,
        "codigo": ln.codigo,
        "articulo": ln.articulo,
        "cantidad": _num(ln.cantidad),
        "moneda": ln.moneda,
        "precio": _num(ln.precio),
        "precio_costo": _num(ln.precio_costo),
        "precio_costo_pdf": _num(ln.precio_costo_pdf if ln.precio_costo_pdf is not None else ln.precio_costo),
        "costo": _num(costo_linea),
        "total_gauss": _num(tg),
        "markup": _markup(tg, costo_linea) if tg is not None else None,
        "item_id": ln.item_id,
        "item_origen": ln.item_origen,
        "producto": descripcion,
        "marca": marca,
        "categoria": categoria,
        "sin_producto": sin_producto,
        "sin_producto_causa": causa_sin_producto(ln.codigo, ln.articulo) if sin_producto else None,
        "override": (
            {
                "estado": override[0].estado,
                "costo_unitario": _num(override[0].costo_unitario),
                "item_id": override[0].item_id,
                "usuario": override[1],
                "updated_at": override[0].updated_at,
            }
            if override
            else None
        ),
    }


def linea_listado(db: Session, ln: VentaFueraOperacionLinea, ver_ganancia: bool, costo: str = "costo_d") -> dict:
    """One line as the list shows it (the answer of the fix endpoints)."""
    return linea_dict(ln, _detalle(db, [ln]), costo, ver_ganancia)


def resumen_sin_producto(db: Session, desde: Optional[date], hasta: Optional[date]) -> list[dict]:
    """`[{causa, lineas, venta}]`: the lines without product by why they have none, most sold first."""
    consulta = select(LN.c.codigo, LN.c.articulo, LN.c.precio).select_from(LN.join(OP, OP.c.id == LN.c.operacion_id))
    consulta = consulta.where(LN.c.item_id.is_(None))
    if desde is not None:
        consulta = consulta.where(OP.c.fecha >= desde)
    if hasta is not None:
        consulta = consulta.where(OP.c.fecha <= hasta)
    causas: dict[str, list] = {}
    for codigo, articulo, precio in db.execute(consulta).all():
        fila = causas.setdefault(causa_sin_producto(codigo, articulo), [0, CERO])
        fila[0] += 1
        fila[1] += precio
    return [
        {"causa": causa, "lineas": n, "venta": _num(venta)}
        for causa, (n, venta) in sorted(causas.items(), key=lambda c: (-c[1][1], c[0]))
    ]


__all__ = ["COSTOS", "ORDENES", "Filtros", "Listado", "linea_listado", "listar", "resumen_sin_producto"]
