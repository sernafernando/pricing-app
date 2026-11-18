"""The Auditoría de stock view of the Publicaciones screen (`GET /ml-publications/view/stock-audit`): one row per BASE
product with what its stock is worth, ERP and Full apart and their total, in USD and in ARS at the day's BNA rate.

Which product is the row (the combo bill of materials, `combo_componentes`, and each item's ERP category, read
through `filters.erp_categories_select`):

* a combo whose own category is PC (47) is a product of its own: one row, never exploded;
* a combo with exactly one notebook component (category 46, not an accessory subcategory) is a variant of that
  notebook: it is listed under it; with more than one (a notebook plus its warranty, both filed as notebooks) the
  base is the most expensive one;
* any other combo of a single component (a pack "x10") is listed under that component;
* any other combo (a kit of several products) is not shown, and counts nowhere;
* a product that is not a combo is its own row.

What a row is worth (owner, 2026-11-17: "Costo x Stock, en USD y en ARS al cambio BNA del día. Sobre los productos
base, no me sumes las variantes como si fueran un producto adicional"): the catalog cost (no VAT) times the
units. ERP: the base product's own ERP stock; a variant's ERP stock is derived from its base, so it is neither shown
nor added. Full: the units at ML's warehouse of the publications linked to the product, each user product counted
once (a classic and a premium listing share one); a variant's Full units add to its base's, worth the variant's own
cost, and in base units (a pack's units times its quantity). The variant row shows its own part.
Stock without cost is never valued as 0 nor hidden in a partial sum (L9): a row or variant with some stock without
cost says `sin_costo` and its values read unknown; the KPI totals add the stock with a cost only and count the rows
left out (`productos_sin_costo`). Without the BNA rate the currency it cannot reach is unknown, in the KPIs too.

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

The Rotación group (Última venta, Ageing, Días de cobertura, Rotación (veces)) is the WHOLE product's whatever the
filter (L2, owner: "Con filtro, usar las ventas de todo el producto"): all its publications' sales over all its stock
(`add_rotation`), the rest of the row being the filtered part.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping, Optional

from sqlalchemy import ARRAY, Integer, Text, bindparam, func, select, text
from sqlalchemy.orm import Session

from app.models.tipo_cambio import TipoCambio
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.groups import NO_GROUP, NO_LABELS, dimension_of
from app.services.ml_daily_metrics.kpi_strip import round_money, round_pp
from app.services.combos.pcs import CAT_PC  # the one PC rule, shared with sell out (`combos.pcs`)
from app.services.ml_publications.view.cost_lines import siso_markups
from app.services.ml_publications.view.filters import (
    T,
    NOTEBOOK_ACCESSORY_SUBCATEGORIES,
    PublicationFilter,
    build_base_select,
    catalog_products_select,
    erp_categories_select,
    joined,
    product_select,
    publication_filter_in,
)
from app.services.ml_publications.view.listing import EMPTY_SUMMARY, Summary, summaries, summary_columns
from app.services.ml_publications.view.markup_service import ItemMarkup, aggregate_nodes, compute_markups
from app.services.ml_publications.view.products import product_pairs
from app.services.ml_publications.view.row_metrics import fulfillment_by_mla, metrics_by_mla
from app.services.pricing_calculator import moneda_de

CAT_NOTEBOOK = 46

PRODUCTO, PC, VARIANTE, PACK, KIT = "producto", "pc", "variante", "pack", "kit"
ACTIVE = "active"

# The sales sorts need ml_metricas.ver, the margin ones also ml_metricas.ver_ganancia (`needs_sales`, `needs_margin`).
SALES_ORDERS = ("unidades_7d", "unidades_30d", "facturado_30d", "ultima_venta", "ageing", "cobertura", "rotacion")
MARGIN_ORDERS = ("total_gauss_30d", "markup_30d", "markup", "markup_siso")
ORDERS = (
    "valor_total",
    "valor_erp",
    "valor_full",
    "unidades_total",
    "unidades_erp",
    "unidades_full",
    "descripcion",
    "promos_aplicadas",
    *SALES_ORDERS,
    *MARGIN_ORDERS,
)


NEVER_SOLD = datetime.min.replace(tzinfo=timezone.utc)


def _last_sale_key(sales: Sales) -> Optional[datetime]:
    """Never sold, with publications, is the oldest last sale of all; no Board row at all is unknown (last)."""
    return sales.last_sale_at or (NEVER_SOLD if sales.any_board_row else None)


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
    return category is not None and category[0] == CAT_NOTEBOOK and category[1] not in NOTEBOOK_ACCESSORY_SUBCATEGORIES


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
    """Units and what they are worth (L9: never a false 0 nor a partial sum shown as whole). A currency's value is
    None when no unit has a known value, and also when some units of it are unknown: units of a product without
    cost (`sin_costo`, both currencies) or a currency the missing BNA rate cannot reach (`usd_unknown` /
    `ars_unknown`)."""

    unidades: int = 0
    usd: Optional[float] = None
    ars: Optional[float] = None
    sin_costo: bool = False
    usd_unknown: bool = False
    ars_unknown: bool = False

    def add(self, units: float, usd: Optional[float], ars: Optional[float]) -> None:
        """Units with the values known for them; a value left None counts nowhere (the KPIs' units-only parts)."""
        self.unidades += int(units)
        if usd is not None:
            self.usd = (self.usd or 0.0) + usd
        if ars is not None:
            self.ars = (self.ars or 0.0) + ars

    def add_part(self, units: float, usd: Optional[float], ars: Optional[float], *, sin_costo: bool) -> None:
        """A stocked part of a row: without cost, or with a currency the rate cannot reach, its value is unknown."""
        if units and sin_costo:
            self.sin_costo = True
        elif units:
            self.usd_unknown |= usd is None
            self.ars_unknown |= ars is None
        self.add(units, usd, ars)

    def plus(self, other: "Money") -> "Money":
        total = Money(
            self.unidades,
            self.usd,
            self.ars,
            self.sin_costo or other.sin_costo,
            self.usd_unknown or other.usd_unknown,
            self.ars_unknown or other.ars_unknown,
        )
        total.add(other.unidades, other.usd, other.ars)
        return total

    def known(self) -> "Money":
        """What the KPI totals add of this part (L9): its units always, its values only when it has a cost (the
        products without cost are counted apart, `productos_sin_costo`); a currency the rate cannot reach stays
        unknown."""
        if self.sin_costo:
            return Money(self.unidades)
        return Money(self.unidades, self.usd, self.ars, False, self.usd_unknown, self.ars_unknown)

    def out(self) -> dict[str, Any]:
        unknown = self.sin_costo
        return {
            "unidades": self.unidades,
            "usd": None if unknown or self.usd_unknown else _round(self.usd),
            "ars": None if unknown or self.ars_unknown else _round(self.ars),
        }


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
    # Última venta / Ageing (rotacion S2): the Board's own per-publication figures, never a second definition. The
    # latest sale of any publication; the ageing of the publications that sold (the least, i.e. since that latest
    # sale) and of the ones that never did (the most, i.e. since the oldest one started).
    last_sale_at: Optional[datetime] = None
    ageing_sold: Optional[int] = None
    ageing_unsold: Optional[int] = None
    # auditoria-stock-niveles S3: the window units shipped by Full, and those with no shipping data (inside ERP);
    # ERP is the window's units minus Full (`board.Board.units_by_fulfillment`)
    full_7d: Decimal = Decimal(0)
    full_30d: Decimal = Decimal(0)
    unknown_7d: Decimal = Decimal(0)
    unknown_30d: Decimal = Decimal(0)

    @property
    def erp_30d(self) -> Decimal:
        return self.units_30d - self.full_30d

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

    def add(
        self, row: board.Row, units_factor: Decimal = Decimal(1), split: Optional[board.ShippingSplit] = None
    ) -> None:
        """A publication's Board row, and its Full split (None: no line in the window, its units, if any, are ERP)."""
        self.any_board_row = True
        self.units_7d += row.windows.get("7d", 0) * units_factor
        self.units_30d += row.windows.get("30d", 0) * units_factor
        if split is not None:
            self.full_7d += split.full_7d * units_factor
            self.full_30d += split.full_30d * units_factor
            self.unknown_7d += split.unknown_7d * units_factor
            self.unknown_30d += split.unknown_30d * units_factor
        self.gross += row.gross
        self.tg += row.tg
        self.mtg += row.mtg
        self.costo += row.costo
        for name in SELL_FIELDS:
            value = getattr(row, name)
            if value is not None:
                setattr(self, name, (getattr(self, name) or 0) + value)
        self._add_series(row, units_factor)
        if row.ageing_days is not None:
            if row.last_sale_at is not None:
                self.ageing_sold = min(
                    row.ageing_days, self.ageing_sold if self.ageing_sold is not None else row.ageing_days
                )
            else:
                self.ageing_unsold = max(row.ageing_days, self.ageing_unsold or 0)
        if row.last_sale_at is not None and (self.last_sale_at is None or row.last_sale_at > self.last_sale_at):
            self.last_sale_at = row.last_sale_at

    def plus(self, other: "Sales") -> "Sales":
        """Two rows' sales added (a Marca or Categoría row, S2): every sum summed, the series day by day, the latest
        last sale, and the ageings as `add` keeps them, so a group reads as if its publications were one row's."""
        total = Sales()
        for name in ("units_7d", "units_30d", "gross", "tg", "mtg", "costo"):
            setattr(total, name, getattr(self, name) + getattr(other, name))
        for name in ("full_7d", "full_30d", "unknown_7d", "unknown_30d"):
            setattr(total, name, getattr(self, name) + getattr(other, name))
        total.any_board_row = self.any_board_row or other.any_board_row
        for name in SELL_FIELDS:
            mine, theirs = getattr(self, name), getattr(other, name)
            setattr(total, name, None if mine is None and theirs is None else (mine or 0) + (theirs or 0))
        days = max(len(self.series_units), len(other.series_units))
        for day in range(days):
            total.series_units.append(
                (self.series_units[day] if day < len(self.series_units) else Decimal(0))
                + (other.series_units[day] if day < len(other.series_units) else Decimal(0))
            )
            total.series_markups.append(
                (self.series_markups[day] if day < len(self.series_markups) else [])
                + (other.series_markups[day] if day < len(other.series_markups) else [])
            )
        sold = [a for a in (self.ageing_sold, other.ageing_sold) if a is not None]
        unsold = [a for a in (self.ageing_unsold, other.ageing_unsold) if a is not None]
        total.ageing_sold = min(sold) if sold else None
        total.ageing_unsold = max(unsold) if unsold else None
        lasts = [at for at in (self.last_sale_at, other.last_sale_at) if at is not None]
        total.last_sale_at = max(lasts) if lasts else None
        return total

    def envio_out(self) -> dict[str, dict[str, int]]:
        """S3: each window's units shipped by Full and the rest (ERP), the ones without shipping data counted apart
        (they are in ERP). ERP is the shown total minus Full, so the two always add up to the number above them."""

        def window(units: Decimal, full: Decimal, unknown: Decimal) -> dict[str, int]:
            return {"erp": int(units) - int(full), "full": int(full), "sin_envio": int(unknown)}

        return {
            "7d": window(self.units_7d, self.full_7d, self.unknown_7d),
            "30d": window(self.units_30d, self.full_30d, self.unknown_30d),
        }

    @property
    def ageing_dias(self) -> Optional[int]:
        """The Board's ageing over the row's publications: days since its last sale, or since its oldest publication
        started when none ever sold (`board`'s `coalesce(max(last_day), min(start_day))`)."""
        return self.ageing_sold if self.ageing_sold is not None else self.ageing_unsold

    @property
    def ultima_venta_dias(self) -> Optional[int]:
        """Days since the last sale: the ageing of a row that sold (the same day count as the Board's)."""
        return self.ageing_sold

    def out(self, with_margin: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "unidades_7d": int(self.units_7d),
            "unidades_30d": int(self.units_30d),
            "facturado_30d": round_money(self.gross),
            "series_units_90d": [int(units) for units in self.series_units],
            "ultima_venta": self.last_sale_at,
            "ultima_venta_dias": self.ultima_venta_dias,
            "ageing_dias": self.ageing_dias,
            "envio": self.envio_out(),
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
    markup_siso: Optional[tuple[float, float]] = None  # the current markup c/ SISO's range (`add_markups`)
    summary: Summary = EMPTY_SUMMARY
    average: Optional["Average"] = None  # its own Full's (`add_rotation`)
    whole: Optional["Whole"] = None  # the whole product's rotation figures, whatever the filter (`add_rotation`)

    @property
    def stock_now(self) -> int:
        """Its stock in its own units: its Full only (its ERP stock is its base's, S4)."""
        return self.full.unidades

    stock_erp = None  # its ERP stock is its base's: no ERP coverage nor rotation of its own

    @property
    def stock_full(self) -> int:
        return self.full.unidades


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
    markup_siso: Optional[tuple[float, float]] = None
    summary: Summary = EMPTY_SUMMARY
    average: Optional["Average"] = None  # its ERP + Full + its variants' Full in base units (`add_rotation`)
    whole: Optional["Whole"] = None  # the whole product's rotation figures, whatever the filter (`add_rotation`)
    group: Optional["GroupKeys"] = None  # its base product's brand and category (`add_groups`)

    @property
    def stock_now(self) -> int:
        return self.total.unidades

    @property
    def stock_erp(self) -> int:
        return self.erp.unidades

    @property
    def stock_full(self) -> int:
        return self.full.unidades

    @property
    def total(self) -> Money:
        return self.erp.plus(self.full)

    @property
    def sin_costo(self) -> bool:
        """Some of its stock (its own ERP or Full, or a variant's Full) has no cost: its values are unknown (L9)."""
        return self.erp.sin_costo or self.full.sin_costo


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
    return {item: (cat, subcat) for item, cat, subcat in db.execute(erp_categories_select(ids)).all()}


def _products(db: Session, ids: Iterable[int]) -> dict[int, Product]:
    ids = sorted(set(ids))
    if not ids:
        return {}
    rows = db.execute(catalog_products_select(ids)).all()
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
    return _assemble(db, pairs, stock_only, rate)


def _assemble(db: Session, pairs: list[tuple[str, int]], stock_only: list[int], rate: Rate) -> Audit:
    """The base rows of these (MLA, product) pairs and stock-only products, with their stock (S3-S6)."""
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

    paired = {product for _, product in pairs}
    for product in linked:
        located = base_of(product)
        if located is None:
            continue
        base, kind = located
        # A variant or pack is listed only with a publication (S3, L2): its ERP stock is the base's, never its own, so a
        # stock-only combo adds nothing, not even its base row (the base comes in on its own stock or publications).
        if product != base and product not in paired:
            continue
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
            r.erp.add_part(stock, *value(r.product, stock, rate), sin_costo=r.product.costo is None)
        own_full = full.get(r.product.item_id, 0)
        if own_full:
            r.full.add_part(own_full, *value(r.product, own_full, rate), sin_costo=r.product.costo is None)
        for v in r.variants.values():
            units = full.get(v.product.item_id, 0)
            if not units:
                continue
            usd, ars = value(v.product, units, rate)
            v.full.add_part(units, usd, ars, sin_costo=v.product.costo is None)
            v.full_unidades_base = int(units * v.cantidad)
            r.full.add_part(v.full_unidades_base, usd, ars, sin_costo=v.product.costo is None)

    with_stock = [r for r in rows.values() if r.erp.unidades > 0 or r.full.unidades > 0]
    return Audit(with_stock, rate, _active(db, {m for r in with_stock for m in r.publications}))


def add_sales(db: Session, audit: "Audit", sell_in_out: bool) -> None:
    """Every row's and variant's sales (module docstring): ONE Board read for all the rows' publications."""
    mlas = sorted({m for r in audit.rows for m in r.publications})
    figures = metrics_by_mla(db, mlas, sell_in_out=sell_in_out)
    # S3: the Full split of the same windows, read once for all the rows (a publication without one is all ERP)
    splits = fulfillment_by_mla(db, mlas) if mlas else {}
    for r in audit.rows:
        for mla in sorted(r.own_publications):
            if (found := figures.get(mla)) is not None:
                r.sales.add(found, split=splits.get(mla))
        for v in r.variants.values():
            for mla in sorted(v.publications):
                if (found := figures.get(mla)) is not None:
                    v.sales.add(found, split=splits.get(mla))
                    r.sales.add(found, v.cantidad, splits.get(mla))


# --- Rotación (rotacion S2, L1): Días de cobertura and Rotación (veces) ------------------------------------------------

COVERAGE_DAYS = 30  # the sales pace: units sold in the last 30 business days (`Sales.units_30d`) per day


@dataclass(frozen=True)
class Average:
    """The average stock of a row over the days photographed in the last 30 (`stock_snapshot.averages`); `dias` = 0:
    no photo yet, the stock now stands in (L1: "with 0 snapshots use current stock and mark it as approximation")."""

    stock: float
    dias: int
    erp: Optional[float] = None  # S4: the ERP part (None: a variant, whose ERP stock is its base's)
    full: float = 0.0  # S4: the Full part


def full_by_product(db: Session) -> dict[int, int]:
    """Every product's Full units, as an unfiltered Auditoría counts them (the daily stock photo's Full)."""
    return _full_units(db, _pairs(db, PublicationFilter()))


@dataclass(frozen=True)
class Whole:
    """The figures of the Rotación group (L2, owner: "Con filtro, usar las ventas de todo el producto"): the whole
    product's sales (all its publications and its variants') over its whole stock, never the filtered part."""

    sales: Sales
    stock: int
    average: Optional[Average]
    stock_erp: Optional[int] = None  # S4: None for a variant (its ERP stock is its base's)
    stock_full: int = 0


def whole_of(r: "Row | Variant | Group") -> Whole:
    """Its whole product's figures; its own until `add_rotation` ran."""
    return r.whole or Whole(r.sales, r.stock_now, r.average, r.stock_erp, r.stock_full)


def _whole_products(db: Session, audit: "Audit") -> dict[int, Row]:
    """The audit's base rows again, built from ALL their publications (no filter): each base, and every combo that
    has it as a component, with its unfiltered pairs (a combo whose base turns out to be another product is built and
    dropped)."""
    bases = {r.product.item_id for r in audit.rows}
    if not bases:
        return {}
    candidates = bases | {combo for combo, parts in _bom(db).items() if any(item in bases for item, _ in parts)}
    pairs = [(mla, product) for mla, product in _pairs(db, PublicationFilter()) if product in candidates]
    whole = _assemble(db, pairs, sorted(bases), audit.rate)
    return {w.product.item_id: w for w in whole.rows if w.product.item_id in bases}


def _add_averages(db: Session, rows: Iterable[Row], today: date) -> None:
    """Every row's and variant's average stock (module docstring): ONE read of the photos for all of them. A base
    row adds its own ERP and Full and each variant's Full in base units, as its stock now does (S4-S6)."""
    from app.services.ml_publications.view.stock_snapshot import averages

    rows = list(rows)
    items = {r.product.item_id for r in rows} | {v.product.item_id for r in rows for v in r.variants.values()}
    found = averages(db, items, today)
    for r in rows:
        if not found.dias:
            r.average = Average(float(r.stock_now), 0, float(r.stock_erp), float(r.stock_full))
            for v in r.variants.values():
                v.average = Average(float(v.stock_now), 0, None, float(v.stock_full))
            continue
        erp, full = found.stock.get(r.product.item_id, (0.0, 0.0))
        for v in r.variants.values():
            own = found.stock.get(v.product.item_id, (0.0, 0.0))[1]
            v.average = Average(own, found.dias, None, own)
            full += own * float(v.cantidad)
        r.average = Average(erp + full, found.dias, erp, full)


def add_rotation(db: Session, audit: "Audit", today: date) -> None:
    """Every row's and variant's Rotación figures, the WHOLE product's whatever the filter (L2): its rows rebuilt
    from all their publications, their sales read from the Board only when the filter left some out (the rows the
    screen already read are reused otherwise), and their average stock (`_add_averages`)."""
    whole = _whole_products(db, audit)
    seen = {m for r in audit.rows for m in r.publications}
    if {m for w in whole.values() for m in w.publications} - seen:
        add_sales(db, Audit(list(whole.values()), audit.rate, frozenset()), sell_in_out=False)
    else:  # the filter left every publication of these products in: the screen's rows are the whole products
        whole = {r.product.item_id: r for r in audit.rows}
    _add_averages(db, whole.values(), today)
    for r in audit.rows:
        w = whole.get(r.product.item_id, r)
        r.whole = Whole(w.sales, w.stock_now, w.average, w.stock_erp, w.stock_full)
        for item, v in r.variants.items():
            wv = w.variants.get(item, v)
            v.whole = Whole(wv.sales, wv.stock_now, wv.average, None, wv.stock_full)


def coverage(stock: int, sold_30d: Decimal) -> Optional[float]:
    """Days the stock lasts at the last 30 days' pace; `inf` with stock and no sale (L1 Q2: "∞"), None with neither."""
    if sold_30d > 0:
        return round(stock * COVERAGE_DAYS / float(sold_30d), 1)
    return float("inf") if stock > 0 else None


def rotation(sold_30d: Decimal, average: Optional[Average]) -> Optional[float]:
    """Units sold in 30 days over the average stock; None (the view's "—") when that average is 0 or unknown."""
    return _per_stock(sold_30d, None if average is None else average.stock)


def _per_stock(sold_30d: Decimal, stock: Optional[float]) -> Optional[float]:
    if stock is None or stock <= 0:
        return None
    return round(float(sold_30d) / stock, 2)


def _coverage_out(stock: Optional[int], sold_30d: Decimal, average: Optional[float]) -> dict[str, Any]:
    """One source's Días de cobertura and Rotación (S4); a source the row has no stock of its own in (a variant's
    ERP) reads nothing."""
    days = None if stock is None else coverage(stock, sold_30d)
    return {
        "dias_cobertura": None if days is None or days == float("inf") else days,
        "cobertura_infinita": days == float("inf"),
        "rotacion": None if stock is None else _per_stock(sold_30d, average),
    }


def rotation_out(whole: Whole) -> dict[str, Any]:
    """The Rotación group's fields, the whole product's (L2): they replace the filtered ones of `Sales.out`."""
    sales, stock, average = whole.sales, whole.stock, whole.average
    days = coverage(stock, sales.units_30d)
    return {
        "ultima_venta": sales.last_sale_at,
        "ultima_venta_dias": sales.ultima_venta_dias,
        "ageing_dias": sales.ageing_dias,
        "dias_cobertura": None if days is None or days == float("inf") else days,
        "cobertura_infinita": days == float("inf"),
        "rotacion": rotation(sales.units_30d, average),
        "stock_promedio": None if average is None else round(average.stock, 2),
        "stock_promedio_dias": None if average is None else average.dias,
        # S4: each source's stock over its own sales (ERP = the sales not shipped by Full)
        "por_origen": {
            "erp": _coverage_out(whole.stock_erp, sales.erp_30d, None if average is None else average.erp),
            "full": _coverage_out(whole.stock_full, sales.full_30d, None if average is None else average.full),
        },
    }


def publication_markups(db: Session, pricing_db: Session, mlas: Iterable[str]) -> Mapping[str, ItemMarkup]:
    """The list markup of each publication (`compute_markups`, the Publicaciones list's own figure)."""
    mlas = sorted(set(mlas))
    return compute_markups(db, pricing_db, item_ids=mlas).items if mlas else {}


def _span(ranges: Iterable[Optional[tuple[float, float]]]) -> Optional[tuple[float, float]]:
    known = [r for r in ranges if r is not None]
    return (min(low for low, _ in known), max(high for _, high in known)) if known else None


def add_markups(db: Session, pricing_db: Session, audit: "Audit") -> None:
    """Every row's and variant's current markup range (module docstring), and the same range of the markup c/ SISO
    (`cost_lines.siso_markups`, the Publicaciones list's own figure); ONE markup read and ONE sell in / sell out read
    for all the rows."""
    members = [(m, str(r.product.item_id)) for r in audit.rows for m in r.own_publications]
    members += [(m, str(v.product.item_id)) for r in audit.rows for v in r.variants.values() for m in v.publications]
    items = publication_markups(db, pricing_db, {m for m, _ in members})
    siso = siso_markups(pricing_db, items) or {}
    nodes = aggregate_nodes(items, members, products=True)
    siso_nodes = aggregate_nodes({m: found.as_item(items[m]) for m, found in siso.items()}, members, products=True)

    def range_of(found: Mapping[str, Any], product: int) -> Optional[tuple[float, float]]:
        node = found.get(str(product))
        if node is None or node.markup_min is None or node.markup_max is None:
            return None
        return node.markup_min, node.markup_max

    for r in audit.rows:
        for v in r.variants.values():
            v.markup = range_of(nodes, v.product.item_id)
            v.markup_siso = range_of(siso_nodes, v.product.item_id)
        r.markup = _span([range_of(nodes, r.product.item_id), *(v.markup for v in r.variants.values())])
        own = range_of(siso_nodes, r.product.item_id)
        r.markup_siso = _span([own, *(v.markup_siso for v in r.variants.values())])


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
    "valor_total": lambda r: r.total.out()["usd"],
    "valor_erp": lambda r: r.erp.out()["usd"],
    "valor_full": lambda r: r.full.out()["usd"],
    "unidades_total": lambda r: r.total.unidades,
    "unidades_erp": lambda r: r.erp.unidades,
    "unidades_full": lambda r: r.full.unidades,
    "descripcion": lambda r: label_of(r).lower(),
    "unidades_7d": lambda r: r.sales.units_7d,
    "unidades_30d": lambda r: r.sales.units_30d,
    "facturado_30d": lambda r: r.sales.gross,
    # the Rotación group: the whole product's figures, as shown (L2)
    "ultima_venta": lambda r: _last_sale_key(whole_of(r).sales),
    "ageing": lambda r: whole_of(r).sales.ageing_dias,
    # infinite coverage (stock, no sale) is the worst: the highest (L1 Q2)
    "cobertura": lambda r: coverage(whole_of(r).stock, whole_of(r).sales.units_30d),
    "rotacion": lambda r: rotation(whole_of(r).sales.units_30d, whole_of(r).average),
    # the figures the view shows; a row without one goes last either way
    "total_gauss_30d": lambda r: r.sales.total_gauss_shown,
    "markup_30d": lambda r: r.sales.markup_shown,
    "markup": lambda r: None if r.markup is None else r.markup[0],
    "markup_siso": lambda r: None if r.markup_siso is None else r.markup_siso[0],
}


# --- Marca and Categoría levels (auditoria-stock-niveles S1-S2) ------------------------------------------------------

MARCA, CATEGORIA = "marca", "categoria"
NIVELES = (MARCA, CATEGORIA, PRODUCTO)


@dataclass(frozen=True)
class GroupKeys:
    """A base product's brand and category as the Agrupado tree keys them (`groups.dimension_of`: trimmed and
    upper-cased by the database, `NO_GROUP` for none), with a name to show for each."""

    marca: str
    marca_nombre: str
    categoria: str
    categoria_nombre: str


def add_groups(db: Session, audit: "Audit") -> None:
    """Every row's brand and category, the BASE product's (a variant is listed under its base, so it counts in its
    base's group): ONE statement. A product missing from the catalog has neither."""
    ids = sorted({r.product.item_id for r in audit.rows})
    found: dict[int, GroupKeys] = {}
    if ids:
        p = T.p
        marca = dimension_of(MARCA, marca=p.marca, categoria=p.categoria, subcategoria_id=None, store_id=None)
        categoria = dimension_of(CATEGORIA, marca=p.marca, categoria=p.categoria, subcategoria_id=None, store_id=None)
        rows = db.execute(
            select(p.item_id, marca.key, func.trim(p.marca), categoria.key, func.trim(p.categoria)).where(
                p.item_id.in_(ids)
            )
        ).all()
        for item, mk, mn, ck, cn in rows:
            found[item] = GroupKeys(mk, _group_name(MARCA, mk, mn), ck, _group_name(CATEGORIA, ck, cn))
    none = GroupKeys(NO_GROUP, NO_LABELS[MARCA], NO_GROUP, NO_LABELS[CATEGORIA])
    for r in audit.rows:
        r.group = found.get(r.product.item_id, none)


def drill_names(audit: "Audit", marca: Optional[str], categoria: Optional[str]) -> dict[str, Optional[str]]:
    """The names of the drilled brand and category as their rows show them (`GroupKeys`), from the drilled rows;
    None for a level not drilled or with no row left."""
    first = audit.rows[0].group if audit.rows and audit.rows[0].group is not None else None
    return {
        MARCA: first.marca_nombre if marca and first else None,
        CATEGORIA: first.categoria_nombre if categoria and first else None,
    }


def _group_name(level: str, key: str, name: Optional[str]) -> str:
    return NO_LABELS[level] if key == NO_GROUP or not name else name


def restrict(audit: "Audit", marca: Optional[str], categoria: Optional[str]) -> "Audit":
    """The audit narrowed to one brand and/or category (a drill into a group row, S1): its rows only, so the KPIs, the
    total and the page are the group's. Needs `add_groups`."""
    rows = [
        r
        for r in audit.rows
        if r.group is not None
        and (marca is None or r.group.marca == marca)
        and (categoria is None or r.group.categoria == categoria)
    ]
    return Audit(rows, audit.rate, audit.active)


@dataclass
class Group:
    """A Marca or Categoría row (S2): its base rows added up with the rules of the base rows. Stock and values are the
    KPI strip's (`Money.known`: the costed values, the rows without cost counted in `productos_sin_costo`); sales are
    summed (a variant's already in base units on its base row, so never twice); coverage and rotation are computed
    on the summed stock, sales and average stock, never an average of the rows' figures."""

    nivel: str
    marca: Optional[str]
    categoria: Optional[str]
    nombre: str
    rows: list[Row]
    categorias: list["Group"] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.erp, self.full = Money(), Money()
        self.sales = Sales()
        self.publications: set[str] = set()
        stock = stock_erp = stock_full = 0
        sales_whole = Sales()
        averages = [whole_of(r).average for r in self.rows]
        for r in self.rows:
            self.erp = self.erp.plus(r.erp.known())
            self.full = self.full.plus(r.full.known())
            self.sales = self.sales.plus(r.sales)
            self.publications |= r.publications
            w = whole_of(r)
            sales_whole = sales_whole.plus(w.sales)
            stock, stock_erp, stock_full = stock + w.stock, stock_erp + (w.stock_erp or 0), stock_full + w.stock_full
        average = None
        if averages and all(a is not None for a in averages):
            average = Average(
                sum(a.stock for a in averages),
                max(a.dias for a in averages),
                sum(a.erp or 0.0 for a in averages),
                sum(a.full for a in averages),
            )
        self.whole = Whole(sales_whole, stock, average, stock_erp, stock_full)
        self.markup = _span(r.markup for r in self.rows)
        self.markup_siso = _span(r.markup_siso for r in self.rows)  # same rule as `markup` (pubml-markup-siso S4)

    @property
    def key(self) -> str:
        if self.nivel == MARCA:
            return f"marca:{self.marca}"
        if self.marca is None:
            return f"categoria:{self.categoria}"
        return f"marca:{self.marca}|categoria:{self.categoria}"

    @property
    def total(self) -> Money:
        return self.erp.plus(self.full)

    @property
    def sin_costo(self) -> int:
        return sum(1 for r in self.rows if r.sin_costo)


def label_of(r: "Row | Group") -> str:
    """The name a row shows (its sort by name)."""
    return r.nombre if isinstance(r, Group) else (r.product.descripcion or "")


def group_rows(rows: list[Row], nivel: str, marca: Optional[str] = None) -> list[Group]:
    """The base rows grouped by `nivel` (`marca`: each brand with its categories; `categoria`: each category, across
    brands, or inside `marca` when the rows were drilled into one: its categories then name it, so opening one
    stays inside that brand), in no particular order (`sort_rows` orders them). Needs `add_groups`."""

    def by(level: str, members: list[Row]) -> dict[str, list[Row]]:
        out: dict[str, list[Row]] = defaultdict(list)
        for r in members:
            out[r.group.marca if level == MARCA else r.group.categoria].append(r)
        return out

    def name(level: str, members: list[Row]) -> str:
        g = members[0].group
        return g.marca_nombre if level == MARCA else g.categoria_nombre

    if nivel == CATEGORIA:
        return [
            Group(CATEGORIA, marca, key, name(CATEGORIA, members), members)
            for key, members in by(CATEGORIA, rows).items()
        ]
    out = []
    for marca, members in by(MARCA, rows).items():
        categorias = [
            Group(CATEGORIA, marca, key, name(CATEGORIA, sub), sub) for key, sub in by(CATEGORIA, members).items()
        ]
        out.append(Group(MARCA, marca, None, name(MARCA, members), members, categorias))
    return out


def group_out(
    g: Group,
    active: frozenset[str],
    started: Optional[frozenset[str]],
    *,
    with_sales: bool = False,
    with_margin: bool = False,
    orden: str = "valor_total",
    descending: bool = True,
) -> dict[str, Any]:
    """A Marca or Categoría row as the endpoint answers it: the product row's columns, added up (`Group`); a brand
    of the Marca level also carries its categories, in the same order as the rows."""
    kinds: dict[str, int] = {}
    states: dict[str, int] = {}
    for r in g.rows:
        for kind, count in r.summary.kind_counts.items():
            kinds[kind] = kinds.get(kind, 0) + count
        for state, count in r.summary.status_counts.items():
            states[state] = states.get(state, 0) + count
    body: dict[str, Any] = {
        "key": g.key,
        "tipo": g.nivel,
        "grupo": {"marca": g.marca, "categoria": g.categoria},
        "descripcion": g.nombre,
        "productos": len(g.rows),
        "productos_sin_costo": g.sin_costo,
        "sin_costo": g.sin_costo > 0,
        "erp": g.erp.out(),
        "full": g.full.out(),
        "total": g.total.out(),
        "publications_count": sum(len(r.own_publications) for r in g.rows),
        "publicacion_activa": bool(g.publications & active),
        "promo_aplicada": None if started is None else bool(g.publications & started),
        "promo_counts": promo_counts(g.publications, started),
        "ventas": {**g.sales.out(with_margin), **rotation_out(g.whole)} if with_sales else None,
        "kind_counts": kinds,
        "status_counts": states,
    }
    if with_margin:
        body["markup_actual"] = _range_out(g.markup)
        body["markup_siso"] = _range_out(g.markup_siso)
    if g.nivel == MARCA:
        body["categorias"] = [
            group_out(c, active, started, with_sales=with_sales, with_margin=with_margin)
            for c in sort_rows(g.categorias, orden, descending, started)
        ]
    return body


def promo_counts(publications: set[str], started: Optional[frozenset[str]]) -> Optional[dict[str, int]]:
    """How many of `publications` have a started promotion (`con`) and how many do not (`sin`), for the Promos
    aplicadas column (promos-fila S2); None when the promotions database could not be read."""
    if started is None:
        return None
    con = len(publications & started)
    return {"con": con, "sin": len(publications) - con}


def sort_rows(rows: list[Any], orden: str, descending: bool, started: Optional[frozenset[str]] = None) -> list[Any]:
    """`rows` (base rows or groups) by `orden`; `promos_aplicadas` counts each row's publications with a started
    promotion, unknown (every row in the product order) without the promotions database."""

    def with_promo(r: Any) -> Optional[int]:
        return None if started is None else len(r.publications & started)

    key = with_promo if orden == "promos_aplicadas" else SORT_KEYS[orden]
    ordered = sorted(rows, key=_tie_key)  # the product id (a group's key) closes every tie
    known = [r for r in ordered if key(r) is not None]
    return sorted(known, key=key, reverse=descending) + [r for r in ordered if key(r) is None]


def _tie_key(r: Any) -> Any:
    return r.key if isinstance(r, Group) else r.product.item_id


def kpis(audit: Audit, started: Optional[frozenset[str]]) -> dict[str, Any]:
    """The view's KPI strip (S7) over every row, not the page. The promo counts are None when the promotions
    database could not be read."""
    erp, full = Money(), Money()
    for r in audit.rows:
        erp = erp.plus(r.erp.known())
        full = full.plus(r.full.known())
    without_active = [r for r in audit.rows if not (r.publications & audit.active)]
    sin_activa_valor = Money()
    for r in without_active:
        sin_activa_valor = sin_activa_valor.plus(r.erp.known()).plus(r.full.known())
    con_promo = None if started is None else sum(1 for r in audit.rows if r.publications & started)
    return {
        "erp": erp.out(),
        "full": full.out(),
        "total": erp.plus(full).out(),
        "productos": len(audit.rows),
        "productos_sin_publicacion_activa": len(without_active),
        # L9: the rows with some stock without cost; the values above leave that stock out (its units stay in).
        "productos_sin_costo": sum(1 for r in audit.rows if r.sin_costo),
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
        "sin_costo": r.sin_costo,
        "publications_count": len(r.own_publications),
        "publicacion_activa": bool(r.publications & active),
        "promo_aplicada": None if started is None else bool(r.publications & started),
        "promo_counts": promo_counts(r.publications, started),
        "params": {"producto": str(p.item_id)},
        "ventas": {**r.sales.out(with_margin), **rotation_out(whole_of(r))} if with_sales else None,
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
                "sin_costo": v.full.sin_costo,
                "publications_count": len(v.publications),
                "params": {"producto": str(v.product.item_id)},
                "ventas": ({**v.sales.out(with_margin), **rotation_out(whole_of(v))} if with_sales else None),
                "kind_counts": v.summary.kind_counts,
                "status_counts": v.summary.status_counts,
                "promo_counts": promo_counts(v.publications, started),
                **(
                    {"markup_actual": _range_out(v.markup), "markup_siso": _range_out(v.markup_siso)}
                    if with_margin
                    else {}
                ),
            }
            for v in sorted(r.variants.values(), key=lambda v: (-(v.full.usd or 0.0), v.product.item_id))
        ],
    }
    if with_margin:
        body["markup_actual"] = _range_out(r.markup)
        body["markup_siso"] = _range_out(r.markup_siso)
    return body


def _range_out(found: Optional[tuple[float, float]]) -> Optional[dict[str, float]]:
    return None if found is None else {"min": round(found[0], 2), "max": round(found[1], 2)}
