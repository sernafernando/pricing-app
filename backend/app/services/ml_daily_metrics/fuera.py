"""Ventas por fuera on the Métricas ML board (vpf-metricas-canal, `canal=fuera|todo`): the sold lines of the GBP PDF
operations (#2291: `ventas_fuera_operaciones` + `ventas_fuera_operacion_lineas`, never `ventas_fuera_ml_metricas`), in
the very columns `sales.lines_source` gives the ML lines, so the board sums both the same way.

Rules (owner, vpf-metricas-canal S2-S12):

- PRODUCT of a line = the `productos_erp` row of the line's STORED `item_id` (vpf-operaciones: set at load by
  `ventas_fuera_pdf.resolucion` -- code trimmed, tb_item, article prefix, remembered mapping -- or by a manual fix).
  A line without one is "sin producto":
  one row per code productos_erp does not have, and one per article text of a line without code (S5). Such a row is
  keyed by a NEGATIVE product id, `-(the lowest line id of its code / article)` over every loaded line, so the board's
  (product, MLA) pairs and its integer product keys need no other change, and the key stays the same whatever the
  period or filters (the CSV export fetches rows by key across sessions). Its title is the article text.
- MLA of a line = `FUERA_MLA`: one pair per product, never an ML publication.
- DAY = the document's `fecha`; `group_date` = that day's business midnight, so the board's ranges and its business
  day read it like an ML accreditation. `group_key` = the document: the operations KPI counts fuera documents (S12).
- COST = Costo D (`precio_costo` x `COSTO_D_FACTOR`, default) or `precio_costo` (`costo=costo`); `precio_costo_pp` is
  never read. Total Gauss = precio - cost, markup = Total Gauss / cost: monto / costo - 1, no commission nor shipping
  (S2). A line with cost 0 counts in Venta and units, never in Total Gauss nor markup (S8); a non-ARS line counts
  units only (S9).
- VENTA (gross) carries VAT like the ML Venta: `gross_with_vat` (S11). The cheque surcharge (`recargo_financiero`)
  never enters it (parent S12).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, List, Optional, Tuple

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    Numeric,
    String,
    and_,
    case,
    cast,
    false,
    func,
    literal,
    null,
    or_,
    select,
)

from app.core.constants import BUSINESS_TIMEZONE
from app.models.producto import ProductoERP
from app.models.venta_fuera_pdf import VentaFueraOperacion, VentaFueraOperacionLinea, VentaFueraPdfCarga
from app.services.ml_daily_metrics.sales import BUSINESS_TZ, NO_PRODUCT, Range, _in_ranges
from app.services.ventas_fuera_pdf.carga import CONDICION_CHEQUE, LARGO_VENDEDOR_IMPRESO, RECARGO_CHEQUE
from app.services.ventas_fuera_pdf.ventas import COSTO_D_FACTOR

CANALES = ("ml", "fuera", "todo")
COSTOS = ("costo_d", "costo")
# The MLA of every fuera pair: a fuera sale has no publication.
FUERA_MLA = "fuera"
# The Argentine VAT rates (%) a rate derived from a document may be (S13), and how far from one it may land
# (percentage points): the header Importe is rounded to the cent.
LEGAL_VAT_RATES = (Decimal("0"), Decimal("2.5"), Decimal("5"), Decimal("10.5"), Decimal("21"), Decimal("27"))
VAT_TOLERANCE_PP = Decimal("0.1")

OP = VentaFueraOperacion.__table__
LN = VentaFueraOperacionLinea.__table__


def _vendedores_guardados(nombres: Tuple[str, ...]) -> Tuple[str, ...]:
    """The stored names the vendedor filter matches: each name as given and as GBP prints it on documents, cut to
    `LARGO_VENDEDOR_IMPRESO` characters (operations store that cut name, while an upload's result and its "Ver
    métricas" link carry the report header's full name)."""
    cortados = (n[:LARGO_VENDEDOR_IMPRESO] for n in nombres if len(n) > LARGO_VENDEDOR_IMPRESO)
    return tuple(dict.fromkeys((*nombres, *cortados)))


@dataclass(frozen=True)
class FueraScope:
    """What narrows the fuera lines: the cost basis and the empresa / vendedor filters (stored text, S4; a vendedor
    also matches its 12-character printed cut, `_vendedores_guardados`)."""

    costo: str = "costo_d"
    empresas: Tuple[str, ...] = ()
    vendedores: Tuple[str, ...] = ()


def _money(value: Any) -> Any:
    return literal(value, Numeric(18, 6))


def gross_with_vat(
    precio: Any, iva: Any, importe: Any, condicion_venta: Any, known_vat: Any, unknown_precio: Any
) -> Any:
    """THE one place a fuera line's Venta gets its VAT (S11, owner: "hay que mostrar con IVA donde va con IVA y sin IVA
    donde va sin IVA"): `precio` (without VAT) x (1 + the line's VAT).

    - A line whose product is known takes its product's `productos_erp.iva` (a percentage: 21.0, 10.5).
    - A line without product (or whose product has no `iva`) takes what its document's header Importe leaves for it:
      Importe = every line x its own VAT, x (1 + `RECARGO_CHEQUE`) on "CHEQUE 30 D" documents. So the header without
      the cheque factor, minus the known lines with their VAT (`known_vat`), over the precio of the lines without a
      known rate (`unknown_precio`), is their VAT factor -- never an assumed 21%.
    - That derived rate counts only when it is a legal AR VAT rate (`LEGAL_VAT_RATES`, within `VAT_TOLERANCE_PP`,
      S13). When it is not (e.g. a cheque document loaded without its summary: no condicion de venta, so the x1.04
      stays in the header), or the document leaves no rate to derive (its lines without a known rate add up to 0),
      the line's Venta is NULL (unknown): it adds nothing to Venta, never a guessed amount, and the board counts it
      (`Board.fuera_unknown_venta`, S14).

    `known_vat` and `unknown_precio` are the document's sums (window over its lines)."""
    rate = cast(iva, Numeric) / literal(100, Numeric)
    cheque = func.upper(condicion_venta).like(f"{CONDICION_CHEQUE}%")
    header = case((cheque, importe / _money(Decimal(1) + RECARGO_CHEQUE)), else_=importe)
    derived = (header - known_vat) / func.nullif(unknown_precio, 0)
    derived_pct = (derived - literal(1, Numeric)) * literal(100, Numeric)
    legal = or_(*(func.abs(derived_pct - _money(vat)) <= _money(VAT_TOLERANCE_PP) for vat in LEGAL_VAT_RATES))
    return case(
        (iva.isnot(None), precio * (literal(1, Numeric) + rate)),
        (legal, precio * derived),
        else_=cast(null(), Numeric),
    )


def _documents() -> Any:
    """Every loaded fuera line (all history: the "sin producto" keys and the per-document VAT sums must not depend on
    the period or a filter) with its document, its product and the document's VAT sums."""
    p = ProductoERP.__table__.alias("fuera_producto")
    by_document = {"partition_by": LN.c.operacion_id}
    known = p.c.iva.isnot(None)
    with_vat = LN.c.precio * (literal(1, Numeric) + cast(p.c.iva, Numeric) / literal(100, Numeric))
    no_code_article = case((LN.c.codigo.is_(None), LN.c.articulo))
    sin_producto = -func.min(LN.c.id).over(partition_by=(LN.c.codigo, no_code_article))
    return (
        select(
            LN.c.operacion_id,
            OP.c.tipo,
            OP.c.letra,
            OP.c.recargo_financiero,
            OP.c.fecha,
            OP.c.empresa,
            OP.c.vendedor,
            LN.c.codigo,
            LN.c.articulo,
            LN.c.cantidad,
            LN.c.moneda,
            LN.c.precio,
            LN.c.precio_costo,
            # Sin producto = no stored product, as the operations list counts it: a line resolved by
            # `tb_item.item_code` (no productos_erp row) has one and is filed under it.
            func.coalesce(LN.c.item_id, sin_producto).label("product"),
            (LN.c.item_id.is_(None)).label("sin_producto"),
            (p.c.item_id.is_(None)).label("sin_erp"),
            gross_with_vat(
                LN.c.precio,
                p.c.iva,
                OP.c.importe,
                OP.c.condicion_venta,
                func.sum(case((known, with_vat), else_=0)).over(**by_document),
                func.sum(case((known, 0), else_=LN.c.precio)).over(**by_document),
            ).label("gross_vat"),
        )
        .select_from(LN.join(OP, OP.c.id == LN.c.operacion_id).outerjoin(p, p.c.item_id == LN.c.item_id))
        .subquery("fuera_docs")
    )


def _group_date(fecha: Any, sqlite: bool) -> Any:
    """The business midnight of `fecha`, as the timestamp the board's ranges and `business_date` read."""
    if sqlite:
        # SQLite keeps UTC wall clocks as text; Buenos Aires has a fixed offset (no DST).
        offset = datetime.now(BUSINESS_TZ).utcoffset() or timedelta(0)
        return func.datetime(fecha, f"{-int(offset.total_seconds() // 3600):+d} hours")
    return func.timezone(BUSINESS_TIMEZONE, cast(fecha, DateTime))


def _cost(d: Any, costo: str) -> Any:
    """A line's cost on the basis `costo`: Costo D (`precio_costo` x `COSTO_D_FACTOR`) or `precio_costo` (S1)."""
    return d.c.precio_costo * _money(COSTO_D_FACTOR) if costo == "costo_d" else d.c.precio_costo


def _narrowed(query: Any, d: Any, scope: FueraScope, product: Optional[int]) -> Any:
    if scope.empresas:
        query = query.where(d.c.empresa.in_(scope.empresas))
    if scope.vendedores:
        query = query.where(d.c.vendedor.in_(_vendedores_guardados(scope.vendedores)))
    if product is not None:
        query = query.where(d.c.product == product)
    return query


def fuera_lines(
    scope: FueraScope,
    *,
    sqlite: bool,
    ranges: Optional[List[Range]] = None,
    product: Optional[int] = None,
    keyed: bool = False,
    tp: bool = False,
) -> Any:
    """The fuera sold lines of `ranges` as a SELECT with `sales.lines_source`'s columns, in its order: `keyed` adds
    `item_row_id` / `order_id` (NULL: no ML line, so no sell in / sell out) and `group_key` (the document); `tp` adds
    the TP shares (NULL: never a TP-store sale)."""
    d = _documents()
    group_date = _group_date(d.c.fecha, sqlite)
    ars = d.c.moneda == "ARS"
    cost = _cost(d, scope.costo)
    # In Total Gauss and the markup: ARS and with a cost (S8, S9).
    counted = and_(ars, d.c.precio_costo != 0)
    margin = case((counted, d.c.precio - cost), else_=0)
    unknown = cast(null(), Numeric)
    query = select(
        *(
            [
                cast(null(), Integer).label("item_row_id"),
                cast(null(), BigInteger).label("order_id"),
                (literal("f:") + cast(d.c.operacion_id, String)).label("group_key"),
            ]
            if keyed
            else []
        ),
        d.c.product.label("product"),
        literal(FUERA_MLA).label("mla"),
        group_date.label("group_date"),
        d.c.fecha.label("day"),
        d.c.cantidad.label("qty"),
        case((ars, d.c.gross_vat), else_=0).label("gross"),
        margin.label("tg"),
        counted.label("tg_known"),
        margin.label("mtg"),
        case((counted, cost), else_=0).label("mcosto"),
        *([unknown.label("tg_tp"), unknown.label("mtg_tp"), unknown.label("mcosto_tp")] if tp else []),
    )
    if ranges is not None:
        query = query.where(_in_ranges(group_date, ranges))
    return _narrowed(query, d, scope, product)


def fuera_last_sales(scope: FueraScope, *, sqlite: bool, product: Optional[int] = None) -> Any:
    """`product`, `mla`, `last_at` of every fuera pair over ALL history (like `sales.last_sales`), plus what names a
    row without a productos_erp product: `fuera_title` (the article text) and `fuera_codigo` (its code, NULL on manual
    lines)."""
    d = _documents()
    query = select(
        d.c.product.label("product"),
        literal(FUERA_MLA).label("mla"),
        func.max(_group_date(d.c.fecha, sqlite)).label("last_at"),
        func.max(d.c.articulo).label("fuera_title"),
        func.max(case((d.c.sin_erp, d.c.codigo))).label("fuera_codigo"),
    )
    if product == NO_PRODUCT:
        # NO_PRODUCT is ML's "sin producto": no fuera line is filed under it.
        query = query.where(false())
    return _narrowed(query, d, scope, product).group_by(d.c.product)


def fuera_options(scope: FueraScope, *, sqlite: bool, ranges: List[Range]) -> Tuple[Any, Any]:
    """The empresa and vendedor option lists of the fuera lines of `ranges` (S15): each narrowed by the OTHER one's
    filter, never by its own, like the board's chips. Two one-column SELECTs of distinct values."""
    d = _documents()
    in_period = _in_ranges(_group_date(d.c.fecha, sqlite), ranges)

    def options(column: Any, other: Any, values: Tuple[str, ...]) -> Any:
        query = select(column).where(in_period).distinct().order_by(column)
        return query.where(other.in_(values)) if values else query

    return (
        options(d.c.empresa, d.c.vendedor, _vendedores_guardados(scope.vendedores)),
        options(d.c.vendedor, d.c.empresa, scope.empresas),
    )


def otro_costo(costo: str) -> str:
    """The cost basis the board is NOT showing (vpf-metricas-canal-fe C3 `kpis.fuera.otro_costo`)."""
    return "costo" if costo == "costo_d" else "costo_d"


def fuera_kpi_lines(scope: FueraScope, *, sqlite: bool, ranges: List[Range]) -> Any:
    """The fuera sold lines of `ranges` with what the "Por fuera" KPI block reads (vpf-metricas-canal-fe C3): the
    document (`operacion_id`, `tipo`, `letra`, its cheque surcharge `recargo_financiero`), the pair (`product`, `mla`)
    to keep only the board's rows, `sin_producto`, the line's Venta with VAT (`gross`, as the board's) and its Total
    Gauss and cost on the OTHER cost basis (`otro_costo`): `otro_margin` / `otro_mcosto`, by the board's rule (ARS
    lines with a cost only)."""
    d = _documents()
    ars = d.c.moneda == "ARS"
    cost = _cost(d, otro_costo(scope.costo))
    counted = and_(ars, d.c.precio_costo != 0)
    query = select(
        d.c.operacion_id,
        d.c.tipo,
        d.c.letra,
        d.c.recargo_financiero,
        d.c.product.label("product"),
        literal(FUERA_MLA).label("mla"),
        d.c.sin_producto,
        case((ars, d.c.gross_vat), else_=0).label("gross"),
        case((counted, d.c.precio - cost), else_=0).label("otro_margin"),
        case((counted, cost), else_=0).label("otro_mcosto"),
    ).where(_in_ranges(_group_date(d.c.fecha, sqlite), ranges))
    return _narrowed(query, d, scope, None)


def fuera_empresa_documentos(scope: FueraScope, *, sqlite: bool, ranges: List[Range]) -> Any:
    """`empresa`, `documentos`: the period's fuera documents per company, narrowed by the vendedor filter, never by
    the empresa one (like the empresa options, S15)."""
    d = _documents()
    query = (
        select(d.c.empresa, func.count(func.distinct(d.c.operacion_id)).label("documentos"))
        .where(_in_ranges(_group_date(d.c.fecha, sqlite), ranges))
        .group_by(d.c.empresa)
        .order_by(d.c.empresa)
    )
    return query.where(d.c.vendedor.in_(_vendedores_guardados(scope.vendedores))) if scope.vendedores else query


def fuera_vendedor_documentos(scope: FueraScope, *, sqlite: bool, ranges: List[Range]) -> Any:
    """`vendedor`, `documentos`: the period's fuera documents per salesperson, narrowed by the empresa filter, never by
    the vendedor one (like the vendedor options, S15)."""
    d = _documents()
    query = (
        select(d.c.vendedor, func.count(func.distinct(d.c.operacion_id)).label("documentos"))
        .where(_in_ranges(_group_date(d.c.fecha, sqlite), ranges))
        .group_by(d.c.vendedor)
        .order_by(d.c.vendedor)
    )
    return query.where(d.c.empresa.in_(scope.empresas)) if scope.empresas else query


def ultimo_pdf(scope: FueraScope) -> Any:
    """`created_at`, `empresa`, `vendedor` of the newest upload that brought a detailed report (of the filtered
    companies): how fresh the fuera figures are."""
    C = VentaFueraPdfCarga.__table__
    query = (
        select(C.c.created_at, C.c.empresa, C.c.vendedor)
        .where(C.c.archivo_detallado.isnot(None))
        .order_by(C.c.created_at.desc(), C.c.id.desc())
        .limit(1)
    )
    return query.where(C.c.empresa.in_(scope.empresas)) if scope.empresas else query


__all__ = [
    "CANALES",
    "COSTOS",
    "COSTO_D_FACTOR",
    "FUERA_MLA",
    "FueraScope",
    "fuera_empresa_documentos",
    "fuera_vendedor_documentos",
    "fuera_kpi_lines",
    "fuera_last_sales",
    "fuera_lines",
    "fuera_options",
    "gross_with_vat",
    "otro_costo",
    "ultimo_pdf",
]
