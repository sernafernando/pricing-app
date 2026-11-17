"""The Auditoría de stock view of the Publicaciones screen (`GET /ml-publications/view/stock-audit`): one row per BASE
product with what its stock is worth, ERP and Full apart and their total, in USD and in ARS at the day's BNA rate.

Which product is the row (the combo bill of materials, `combo_componentes`, and the ERP category of `tb_item`, its
first row by `comp_id`, as `producto_maestro` reads it):

* a combo whose own category is PC (47) is a product of its own: one row, never exploded;
* a combo with exactly one notebook component (category 46, not an accessory subcategory) is a variant of that
  notebook: it is listed under it; with more than one (a notebook plus its warranty, both filed as notebooks) the
  base is the most expensive one;
* any other combo of a single component (a pack "x10") is listed under that component;
* any other combo (a kit of several products) is not shown, and counts nowhere;
* a product that is not a combo is its own row.

What a row is worth (owner, 2026-11-17: "Costo x Stock, en USD y en ARS al cambio BNA del día. Sobre los productos
base, no me sumes las variantes como si fueran un producto adicional"): `productos_erp.costo` (no VAT) times the
units. ERP: the base product's own ERP stock; a variant's ERP stock is derived from its base, so it is neither shown
nor added. Full: the units at ML's warehouse of the publications linked to the product, each user product counted
once (a classic and a premium listing share one); a variant's Full units add to its base's, worth the variant's own
cost, and in base units (a pack's units times its quantity). The variant row shows its own part.

The publications are the ones the screen's filter selects (`build_base_select`), linked as the Producto view links
them (`products.product_pairs`); when the filter asks nothing of the publications, the products with stock and no
publication at all are rows too (`filters.product_select`, the "Sin MLA" products). Only rows with stock are listed.

Sales (owner, 2026-11-17, L3): each publication's Board row over the last 30 business days (`row_metrics`, what
`/items` shows for it), summed per row as the Producto view sums them: a variant's units in base units on its base row
(a pack's times its quantity), money summed, the markups the Board's ratio of the sums (`board.markup_of`,
`board.SellInOut`), never an average of percentages. Nothing is written.

The 90-day trends (L6): the units summed day by day like the sales (base units on a base row); a day's markup is the
average of its publications' markups weighted by their units that day (the Board hands each publication's daily
markup, not its numerator and cost, so the ratio of the sums cannot be rebuilt here); a day with no markup stays empty.

The current markup (`markup_actual`, ml_metricas.ver_ganancia): the range of the list markup (`compute_markups`, what
the Publicaciones list shows) over the row's publications, each read for its own product (`aggregate_nodes`), as the
Agrupado tree's nodes show it: a range, never an average. Tipo and Estado: the row's publications counted by kind and
by status (`listing.summary_columns`), a base row over its own and its variants' publications.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping, Optional

from sqlalchemy import ARRAY, Integer, Text, bindparam, select, text
from sqlalchemy.orm import Session

from app.models.tipo_cambio import TipoCambio
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.kpi_strip import round_money, round_pp
from app.services.ml_publications.view.filters import (
    T,
    PublicationFilter,
    build_base_select,
    joined,
    product_select,
    publication_filter_in,
)
from app.services.ml_publications.view.listing import EMPTY_SUMMARY, Summary, summaries, summary_columns
from app.services.ml_publications.view.markup_service import ItemMarkup, aggregate_nodes, compute_markups
from app.services.ml_publications.view.products import product_pairs
from app.services.ml_publications.view.row_metrics import metrics_by_mla
from app.services.pricing_calculator import moneda_de
from app.services.producto_specs.campos import SUBCATEGORIAS_EXCLUIDAS

CAT_NOTEBOOK = 46
CAT_PC = 47

PRODUCTO, PC, VARIANTE, PACK, KIT = "producto", "pc", "variante", "pack", "kit"
ACTIVE = "active"

# The sales sorts need ml_metricas.ver, the margin ones also ml_metricas.ver_ganancia (`needs_sales`, `needs_margin`).
SALES_ORDERS = ("unidades_7d", "unidades_30d", "facturado_30d")
MARGIN_ORDERS = ("total_gauss_30d", "markup_30d", "markup")
ORDERS = (
    "valor_total",
    "valor_erp",
    "valor_full",
    "unidades_total",
    "unidades_erp",
    "unidades_full",
    "descripcion",
    *SALES_ORDERS,
    *MARGIN_ORDERS,
)


def needs_sales(orden: str) -> bool:
    return orden in SALES_ORDERS or orden in MARGIN_ORDERS


def needs_margin(orden: str) -> bool:
    return orden in MARGIN_ORDERS


@dataclass(frozen=True)
class ComboKind:
    """What a combo is in the audit: `pc`, `variante` / `pack` of `base` (`cantidad` base units each), or `kit`."""

    kind: str
    base: Optional[int] = None
    cantidad: Decimal = Decimal(1)


def is_notebook(category: Optional[tuple[Optional[int], Optional[int]]]) -> bool:
    return category is not None and category[0] == CAT_NOTEBOOK and category[1] not in SUBCATEGORIAS_EXCLUIDAS


def classify_combos(
    components: dict[int, list[tuple[int, Decimal]]],
    categories: dict[int, tuple[Optional[int], Optional[int]]],
    costs: dict[int, Optional[float]],
) -> dict[int, ComboKind]:
    """Each combo of `components` (combo -> [(component, quantity)]) as the module docstring says."""
    kinds: dict[int, ComboKind] = {}
    for combo, parts in components.items():
        own = categories.get(combo)
        notebooks = [(item, qty) for item, qty in parts if is_notebook(categories.get(item))]
        if own is not None and own[0] == CAT_PC:
            kinds[combo] = ComboKind(PC)
        elif notebooks:
            item, qty = max(notebooks, key=lambda part: (costs.get(part[0]) or 0, -part[0]))
            kinds[combo] = ComboKind(VARIANTE, item, qty)
        elif len(parts) == 1:
            kinds[combo] = ComboKind(PACK, parts[0][0], parts[0][1])
        else:
            kinds[combo] = ComboKind(KIT)
    return kinds


@dataclass(frozen=True)
class Rate:
    usd_ars: Optional[float]
    fecha: Optional[date]


@dataclass
class Money:
    """Units and what they are worth; a value is None when no unit has a known cost (never a false 0)."""

    unidades: int = 0
    usd: Optional[float] = None
    ars: Optional[float] = None

    def add(self, units: float, usd: Optional[float], ars: Optional[float]) -> None:
        self.unidades += int(units)
        if usd is not None:
            self.usd = (self.usd or 0.0) + usd
        if ars is not None:
            self.ars = (self.ars or 0.0) + ars

    def plus(self, other: "Money") -> "Money":
        total = Money(self.unidades, self.usd, self.ars)
        total.add(other.unidades, other.usd, other.ars)
        return total

    def out(self) -> dict[str, Any]:
        return {"unidades": self.unidades, "usd": _round(self.usd), "ars": _round(self.ars)}


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


SELL_FIELDS = ("sell_in", "sell_out", "m_sell_in", "m_sell_out", "sell_in_lineas", "sell_out_lineas")


@dataclass
class Sales:
    """A row's Board figures summed (`board.SellInOut` reads the sell fields by name, as on a Board row)."""

    units_7d: Decimal = Decimal(0)
    units_30d: Decimal = Decimal(0)
    gross: Decimal = Decimal(0)
    tg: Decimal = Decimal(0)
    mtg: Decimal = Decimal(0)
    costo: Decimal = Decimal(0)
    any_board_row: bool = False
    sell_in: Optional[Decimal] = None
    sell_out: Optional[Decimal] = None
    m_sell_in: Optional[Decimal] = None
    m_sell_out: Optional[Decimal] = None
    sell_in_lineas: Optional[int] = None
    sell_out_lineas: Optional[int] = None
    series_units: list[Decimal] = field(default_factory=list)
    # per day: the (markup, units) of each publication with a markup that day
    series_markups: list[list[tuple[float, Decimal]]] = field(default_factory=list)

    def _add_series(self, row: board.Row, units_factor: Decimal) -> None:
        days = len(row.series_units)
        while len(self.series_units) < days:
            self.series_units.append(Decimal(0))
            self.series_markups.append([])
        for day, units in enumerate(row.series_units):
            self.series_units[day] += units * units_factor
            markup = row.series_markup[day] if day < len(row.series_markup) else None
            if markup is not None:
                self.series_markups[day].append((markup, units * units_factor))

    def markup_series(self) -> list[Optional[float]]:
        """Each day's markup weighted by its units (a day with markups and no units: their plain average)."""
        out: list[Optional[float]] = []
        for points in self.series_markups:
            weight = sum(units for _, units in points)
            if not points:
                out.append(None)
            elif weight:
                out.append(round(float(sum(Decimal(str(m)) * units for m, units in points) / weight), 1))
            else:
                out.append(round(sum(m for m, _ in points) / len(points), 1))
        return out

    @property
    def total_gauss_shown(self) -> Optional[Decimal]:
        """The Total Gauss the view shows: with sell in / out applied where it applies, else the plain one."""
        if not self.any_board_row:
            return None
        applied = board.SellInOut.total_gauss_sell(self)
        return self.tg if applied is None else applied

    @property
    def markup_shown(self) -> Optional[Decimal]:
        if not self.any_board_row:
            return None
        applied = board.SellInOut.markup_sell(self)
        return board.markup_of(self.mtg, self.costo) if applied is None else applied

    def add(self, row: board.Row, units_factor: Decimal = Decimal(1)) -> None:
        self.any_board_row = True
        self.units_7d += row.windows.get("7d", 0) * units_factor
        self.units_30d += row.windows.get("30d", 0) * units_factor
        self.gross += row.gross
        self.tg += row.tg
        self.mtg += row.mtg
        self.costo += row.costo
        for name in SELL_FIELDS:
            value = getattr(row, name)
            if value is not None:
                setattr(self, name, (getattr(self, name) or 0) + value)
        self._add_series(row, units_factor)

    def out(self, with_margin: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "unidades_7d": int(self.units_7d),
            "unidades_30d": int(self.units_30d),
            "facturado_30d": round_money(self.gross),
            "series_units_90d": [int(units) for units in self.series_units],
        }
        if with_margin:
            body["series_markup_90d"] = self.markup_series()
            known = self.any_board_row
            body["total_gauss_30d"] = round_money(self.tg) if known else None
            body["markup_30d"] = round_pp(board.markup_of(self.mtg, self.costo)) if known else None
            # None where neither sell in nor sell out applies (never a copy of the figures without them)
            body["total_gauss_sell_30d"] = round_money(board.SellInOut.total_gauss_sell(self))
            body["markup_sell_30d"] = round_pp(board.SellInOut.markup_sell(self))
        return body


@dataclass
class Product:
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    marca: Optional[str]
    stock: Optional[int]
    costo: Optional[float]
    moneda: str


@dataclass
class Variant:
    product: Product
    kind: str
    cantidad: Decimal
    full: Money = field(default_factory=Money)
    full_unidades_base: int = 0
    publications: set[str] = field(default_factory=set)
    sales: Sales = field(default_factory=Sales)
    markup: Optional[tuple[float, float]] = None  # the current markup's range (`add_markups`)
    summary: Summary = EMPTY_SUMMARY


@dataclass
class Row:
    product: Product
    kind: str
    erp: Money = field(default_factory=Money)
    full: Money = field(default_factory=Money)
    publications: set[str] = field(default_factory=set)  # its own and its variants'
    own_publications: set[str] = field(default_factory=set)
    variants: dict[int, Variant] = field(default_factory=dict)
    sales: Sales = field(default_factory=Sales)
    markup: Optional[tuple[float, float]] = None
    summary: Summary = EMPTY_SUMMARY

    @property
    def total(self) -> Money:
        return self.erp.plus(self.full)


def read_rate(db: Session) -> Rate:
    """The USD selling rate the BNA job stores (`tipo_cambio`): today's, else the latest, with its date."""
    row = (
        db.query(TipoCambio.venta, TipoCambio.fecha)
        .filter(TipoCambio.moneda == "USD")
        .order_by(TipoCambio.fecha.desc())
        .first()
    )
    return Rate(usd_ars=row[0], fecha=row[1]) if row else Rate(None, None)


def value(product: Product, units: float, rate: Rate) -> tuple[Optional[float], Optional[float]]:
    """`units` of `product` at its cost, in USD and in ARS (no cost: unknown; USD <-> ARS needs the rate)."""
    if product.costo is None or not units:
        return (0.0, 0.0) if product.costo is not None else (None, None)
    amount = product.costo * units
    if moneda_de(product.moneda) == "USD":
        return amount, (amount * rate.usd_ars if rate.usd_ars else None)
    return (amount / rate.usd_ars if rate.usd_ars else None), amount


def _pairs(db: Session, f: PublicationFilter) -> list[tuple[str, int]]:
    """(MLA, linked product) of the publications the filter selects, as the Producto view links them."""
    mlas = build_base_select(f, T.i.item_id.label("mla")).subquery("mlas")
    query = product_pairs(f, mlas, mlas.c.mla, lambda pl: pl.c.producto_item_id.label("product"))
    return [(mla, product) for mla, product in db.execute(query).all() if product is not None]


_FULL_SQL = text("""
    SELECT p.product, sum(st.full_quantity) AS full_units
    FROM (
        SELECT DISTINCT x.product, COALESCE(v.user_product_id, i.user_product_id) AS up
        FROM unnest(:mlas, :products) AS x(mla, product)
        JOIN ml_items i ON i.item_id = x.mla
        LEFT JOIN ml_item_product_links l
               ON l.item_id = x.mla AND l.producto_item_id = x.product AND l.variation_id <> 0
        LEFT JOIN ml_item_variations v
               ON v.item_id = l.item_id AND v.variation_id = l.variation_id AND v.gone_at IS NULL
    ) p
    JOIN ml_user_product_stock st ON st.user_product_id = p.up
    WHERE st.full_quantity > 0
    GROUP BY p.product
""").bindparams(bindparam("mlas", type_=ARRAY(Text)), bindparam("products", type_=ARRAY(Integer)))


def _full_units(db: Session, pairs: list[tuple[str, int]]) -> dict[int, int]:
    """Units at ML's warehouse per product: its publications' user products (the variation's when linked per
    variation), each counted once."""
    if not pairs:
        return {}
    rows = db.execute(_FULL_SQL, {"mlas": [m for m, _ in pairs], "products": [p for _, p in pairs]}).all()
    return {product: int(units) for product, units in rows}


def _bom(db: Session) -> dict[int, list[tuple[int, Decimal]]]:
    components: dict[int, list[tuple[int, Decimal]]] = defaultdict(list)
    for combo, item, qty in db.execute(
        text("SELECT combo_item_id, componente_item_id, cantidad FROM combo_componentes")
    ).all():
        components[combo].append((item, Decimal(qty)))
    return components


def _categories(db: Session, ids: Iterable[int]) -> dict[int, tuple[Optional[int], Optional[int]]]:
    ids = sorted(set(ids))
    if not ids:
        return {}
    rows = db.execute(
        text(
            "SELECT DISTINCT ON (item_id) item_id, cat_id, subcat_id FROM tb_item "
            "WHERE item_id = ANY(:ids) ORDER BY item_id, comp_id"
        ).bindparams(bindparam("ids", type_=ARRAY(Integer))),
        {"ids": ids},
    ).all()
    return {item: (cat, subcat) for item, cat, subcat in rows}


def _products(db: Session, ids: Iterable[int]) -> dict[int, Product]:
    ids = sorted(set(ids))
    if not ids:
        return {}
    rows = db.execute(
        select(T.p.item_id, T.p.codigo, T.p.descripcion, T.p.marca, T.p.stock, T.p.costo, T.p.moneda_costo).where(
            T.p.item_id.in_(ids)
        )
    ).all()
    return {r[0]: Product(r[0], r[1], r[2], r[3], r[4], r[5], moneda_de(r[6])) for r in rows}


@dataclass
class Audit:
    rows: list[Row]
    rate: Rate
    active: frozenset[str]


def build(db: Session, f: PublicationFilter, rate: Rate) -> Audit:
    """Every base row with stock under the filter (module docstring)."""
    pairs = _pairs(db, f)
    stock_only: list[int] = []
    if publication_filter_in(f) is None:
        stock_only = [
            item for (item,) in db.execute(product_select(replace(f, sin_mla=True), T.p.item_id).where(T.p.stock > 0))
        ]
    components = _bom(db)
    linked = {product for _, product in pairs} | set(stock_only)
    combo_ids = [p for p in linked if p in components]
    involved = set(combo_ids) | {item for combo in combo_ids for item, _ in components[combo]}
    costs = {p.item_id: p.costo for p in _products(db, involved).values()}
    kinds = classify_combos({c: components[c] for c in combo_ids}, _categories(db, involved), costs)

    def base_of(product: int) -> Optional[tuple[int, str]]:
        kind = kinds.get(product)
        if kind is None:
            return product, PRODUCTO
        if kind.kind == PC:
            return product, PC
        if kind.kind == KIT:
            return None
        return kind.base, kind.kind

    bases = {b[0] for p in linked if (b := base_of(p)) is not None}
    catalog = _products(db, bases | linked)
    full = _full_units(db, pairs)
    rows: dict[int, Row] = {}

    def row(base: int, kind: str) -> Optional[Row]:
        if base not in rows:
            product = catalog.get(base) or Product(base, None, None, None, None, None, "ARS")
            rows[base] = Row(product, PC if kind == PC else PRODUCTO)
        return rows[base]

    for product in linked:
        located = base_of(product)
        if located is None:
            continue
        base, kind = located
        r = row(base, kind)
        if product == base:
            continue
        variant_product = catalog.get(product) or Product(product, None, None, None, None, None, "ARS")
        r.variants.setdefault(product, Variant(variant_product, kind, kinds[product].cantidad))

    for mla, product in pairs:
        located = base_of(product)
        if located is None:
            continue
        r = rows[located[0]]
        r.publications.add(mla)
        if product == located[0]:
            r.own_publications.add(mla)
        else:
            r.variants[product].publications.add(mla)

    for r in rows.values():
        stock = r.product.stock or 0
        if stock > 0:
            r.erp.add(stock, *value(r.product, stock, rate))
        own_full = full.get(r.product.item_id, 0)
        if own_full:
            r.full.add(own_full, *value(r.product, own_full, rate))
        for v in r.variants.values():
            units = full.get(v.product.item_id, 0)
            if not units:
                continue
            usd, ars = value(v.product, units, rate)
            v.full.add(units, usd, ars)
            v.full_unidades_base = int(units * v.cantidad)
            r.full.add(v.full_unidades_base, usd, ars)

    with_stock = [r for r in rows.values() if r.erp.unidades > 0 or r.full.unidades > 0]
    return Audit(with_stock, rate, _active(db, {m for r in with_stock for m in r.publications}))


def add_sales(db: Session, audit: "Audit", sell_in_out: bool) -> None:
    """Every row's and variant's sales (module docstring): ONE Board read for all the rows' publications."""
    figures = metrics_by_mla(db, sorted({m for r in audit.rows for m in r.publications}), sell_in_out=sell_in_out)
    for r in audit.rows:
        for mla in sorted(r.own_publications):
            if (found := figures.get(mla)) is not None:
                r.sales.add(found)
        for v in r.variants.values():
            for mla in sorted(v.publications):
                if (found := figures.get(mla)) is not None:
                    v.sales.add(found)
                    r.sales.add(found, v.cantidad)


def publication_markups(db: Session, pricing_db: Session, mlas: Iterable[str]) -> Mapping[str, ItemMarkup]:
    """The list markup of each publication (`compute_markups`, the Publicaciones list's own figure)."""
    mlas = sorted(set(mlas))
    return compute_markups(db, pricing_db, item_ids=mlas).items if mlas else {}


def _span(ranges: Iterable[Optional[tuple[float, float]]]) -> Optional[tuple[float, float]]:
    known = [r for r in ranges if r is not None]
    return (min(low for low, _ in known), max(high for _, high in known)) if known else None


def add_markups(db: Session, pricing_db: Session, audit: "Audit") -> None:
    """Every row's and variant's current markup range (module docstring); ONE markup read for all the rows."""
    members = [(m, str(r.product.item_id)) for r in audit.rows for m in r.own_publications]
    members += [(m, str(v.product.item_id)) for r in audit.rows for v in r.variants.values() for m in v.publications]
    items = publication_markups(db, pricing_db, {m for m, _ in members})
    nodes = aggregate_nodes(items, members, products=True)

    def range_of(product: int) -> Optional[tuple[float, float]]:
        node = nodes.get(str(product))
        if node is None or node.markup_min is None or node.markup_max is None:
            return None
        return node.markup_min, node.markup_max

    for r in audit.rows:
        for v in r.variants.values():
            v.markup = range_of(v.product.item_id)
        r.markup = _span([range_of(r.product.item_id), *(v.markup for v in r.variants.values())])


def add_summaries(db: Session, audit: "Audit") -> None:
    """Every row's and variant's Tipo and Estado (`listing.summaries`): ONE statement over all their publications."""
    mlas = sorted({m for r in audit.rows for m in r.publications})
    if not mlas:
        return
    pubs = select(T.i.item_id.label("k"), *summary_columns()).select_from(joined()).where(T.i.item_id.in_(mlas))
    by_mla = summaries(db, pubs.subquery("audit_pubs"))

    def merged(publications: set[str]) -> Summary:
        kinds: dict[str, int] = {}
        states: dict[str, int] = {}
        for mla in publications:
            found = by_mla.get(mla)
            if found is None:
                continue
            for kind, count in found.kind_counts.items():
                kinds[kind] = kinds.get(kind, 0) + count
            for state, count in found.status_counts.items():
                states[state] = states.get(state, 0) + count
        return Summary(kinds, states, None, None)

    for r in audit.rows:
        r.summary = merged(r.publications)
        for v in r.variants.values():
            v.summary = merged(v.publications)


def _active(db: Session, mlas: set[str]) -> frozenset[str]:
    if not mlas:
        return frozenset()
    rows = db.execute(select(T.i.item_id).where(T.i.item_id.in_(sorted(mlas)), T.i.status == ACTIVE)).all()
    return frozenset(m for (m,) in rows)


SORT_KEYS: dict[str, Callable[[Row], Any]] = {
    "valor_total": lambda r: r.total.usd or 0.0,
    "valor_erp": lambda r: r.erp.usd or 0.0,
    "valor_full": lambda r: r.full.usd or 0.0,
    "unidades_total": lambda r: r.total.unidades,
    "unidades_erp": lambda r: r.erp.unidades,
    "unidades_full": lambda r: r.full.unidades,
    "descripcion": lambda r: (r.product.descripcion or "").lower(),
    "unidades_7d": lambda r: r.sales.units_7d,
    "unidades_30d": lambda r: r.sales.units_30d,
    "facturado_30d": lambda r: r.sales.gross,
    # the figures the view shows; a row without one goes last either way
    "total_gauss_30d": lambda r: r.sales.total_gauss_shown,
    "markup_30d": lambda r: r.sales.markup_shown,
    "markup": lambda r: None if r.markup is None else r.markup[0],
}


def sort_rows(rows: list[Row], orden: str, descending: bool) -> list[Row]:
    key = SORT_KEYS[orden]
    ordered = sorted(rows, key=lambda r: r.product.item_id)  # the product id closes every tie
    known = [r for r in ordered if key(r) is not None]
    return sorted(known, key=key, reverse=descending) + [r for r in ordered if key(r) is None]


def kpis(audit: Audit, started: Optional[frozenset[str]]) -> dict[str, Any]:
    """The view's KPI strip (S7) over every row, not the page. The promo counts are None when the promotions
    database could not be read."""
    erp, full = Money(), Money()
    for r in audit.rows:
        erp.add(r.erp.unidades, r.erp.usd, r.erp.ars)
        full.add(r.full.unidades, r.full.usd, r.full.ars)
    without_active = [r for r in audit.rows if not (r.publications & audit.active)]
    sin_activa_valor = Money()
    for r in without_active:
        sin_activa_valor = sin_activa_valor.plus(r.total)
    con_promo = None if started is None else sum(1 for r in audit.rows if r.publications & started)
    return {
        "erp": erp.out(),
        "full": full.out(),
        "total": erp.plus(full).out(),
        "productos": len(audit.rows),
        "productos_sin_publicacion_activa": len(without_active),
        "valor_sin_publicacion_activa": sin_activa_valor.out(),
        "productos_con_promo_aplicada": con_promo,
        "productos_sin_promo_aplicada": None if con_promo is None else len(audit.rows) - con_promo,
    }


def row_out(
    r: Row,
    active: frozenset[str],
    started: Optional[frozenset[str]],
    *,
    with_sales: bool = False,
    with_margin: bool = False,
) -> dict[str, Any]:
    """One row as the endpoint answers it; `ventas` is null without `ml_metricas.ver` (`with_sales`), its profit and
    markups present only with `ml_metricas.ver_ganancia` (`with_margin`)."""
    p = r.product
    body = {
        "key": str(p.item_id),
        "product_item_id": p.item_id,
        "tipo": r.kind,
        "codigo": p.codigo,
        "descripcion": p.descripcion or f"Producto #{p.item_id}",
        "marca": p.marca,
        "costo": p.costo,
        "moneda_costo": p.moneda,
        "erp": r.erp.out(),
        "full": r.full.out(),
        "total": r.total.out(),
        "publications_count": len(r.own_publications),
        "publicacion_activa": bool(r.publications & active),
        "promo_aplicada": None if started is None else bool(r.publications & started),
        "params": {"producto": str(p.item_id)},
        "ventas": r.sales.out(with_margin) if with_sales else None,
        "kind_counts": r.summary.kind_counts,
        "status_counts": r.summary.status_counts,
        "variantes": [
            {
                "key": str(v.product.item_id),
                "product_item_id": v.product.item_id,
                "tipo": v.kind,
                "codigo": v.product.codigo,
                "descripcion": v.product.descripcion or f"Producto #{v.product.item_id}",
                "cantidad": float(v.cantidad),
                "costo": v.product.costo,
                "moneda_costo": v.product.moneda,
                "full": v.full.out(),
                "full_unidades_base": v.full_unidades_base,
                "publications_count": len(v.publications),
                "params": {"producto": str(v.product.item_id)},
                "ventas": v.sales.out(with_margin) if with_sales else None,
                "kind_counts": v.summary.kind_counts,
                "status_counts": v.summary.status_counts,
                **({"markup_actual": _range_out(v.markup)} if with_margin else {}),
            }
            for v in sorted(r.variants.values(), key=lambda v: (-(v.full.usd or 0.0), v.product.item_id))
        ],
    }
    if with_margin:
        body["markup_actual"] = _range_out(r.markup)
    return body


def _range_out(found: Optional[tuple[float, float]]) -> Optional[dict[str, float]]:
    return None if found is None else {"min": round(found[0], 2), "max": round(found[1], 2)}
