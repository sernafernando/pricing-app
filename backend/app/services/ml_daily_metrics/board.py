"""The Métricas ML board (ODD `metricas-ml-tablero` T3): one row per PRODUCT
(or per PUBLICATION), with sales windows, markup now vs before, 90-day daily
series for the sparklines, last sale and ageing.

Read path, deliberately boring:

1. The universe is (product, MLA) PAIRS: every publication the ERP mirror
   knows (`tb_mercadolibre_items_publicados`, product = its `item_id`), plus
   any pair the rollup sold in the windows read here that has no
   publication row (it still sold; it shows as "sin tienda / sin estado").
2. Every money/unit number comes from `ml_product_daily_metrics` (SUMS), read
   in ONE query for the days the board needs, then reduced in Python. The
   only exception is the rolling 24h window, which the daily rollup cannot
   answer: it reads the orders accredited in the last 24h directly.
3. Filters select pairs (store, publication status/type, product facets,
   search); a row is the sum of its surviving pairs. Alerts filter rows.
   Every facet count is computed with its OWN axis cleared, the same rule
   the Ventas ML chips follow.

Markup is ALWAYS `SUM(total_gauss) / SUM(costo) x 100` over the selected
rows/days, never an average of percentages; no cost means no markup (None),
never 0.

The store is the publication's CURRENT `mlp_official_store_id` (decision in
the ODD doc): a publication that moved store takes its history with it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_daily_metrics import MlProductDailyMetrics
from app.models.ml_group_metrics import MlGroupMetrics
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.producto import ProductoERP
from app.services.ml_daily_metrics.rollup import BUSINESS_TZ, NO_PRODUCT, business_day
from app.services.ml_publication_status_service import resolve_publication_status
from app.services.ml_sales_query.filters import NO_STORE, _resolve_pm_pairs

GROUP_BY = ("product", "publication")
COMPARE = ("periodo_anterior", "anio_anterior")
PUB_STATUSES = ("active", "paused", "closed", "under_review")
PUB_TYPES = ("clasica", "premium", "catalogo", "full")
ALERTS = ("sin_ventas_30d", "ageing_60d", "margen_cayendo")
SORTS = (
    "gross",
    "units",
    "units_24h",
    "units_3d",
    "units_7d",
    "units_15d",
    "units_30d",
    "total_gauss",
    "markup",
    "markup_delta",
    "last_sale",
    "ageing",
    "title",
)
MARGIN_SORTS = ("total_gauss", "markup", "markup_delta")
SERIES_DAYS = 90
WINDOWS = (("3d", 3), ("7d", 7), ("15d", 15), ("30d", 30))
AGEING_ALERT_DAYS = 60
# "Margen cayendo": the period's markup is at least this many points below the
# comparison period's (decision recorded in the ODD doc).
FALLING_MARGIN_PP = Decimal("-1")
LISTING_TYPES = {"gold_special": "clasica", "gold_pro": "premium"}


def now_utc() -> datetime:
    """The board's clock -- one seam so tests can freeze it."""
    return datetime.now(timezone.utc)


def today_business() -> date:
    return now_utc().astimezone(BUSINESS_TZ).date()


@dataclass(frozen=True)
class BoardFilter:
    date_from: date
    date_to: date
    compare: str = "periodo_anterior"
    group_by: str = "product"
    stores: Tuple[str, ...] = ()
    marcas: Tuple[str, ...] = ()
    subcategorias: Tuple[int, ...] = ()
    pms: Tuple[int, ...] = ()
    q: Optional[str] = None
    pub_status: Tuple[str, ...] = ()
    pub_type: Tuple[str, ...] = ()
    alerts: Tuple[str, ...] = ()
    sort: str = "gross"
    sort_desc: bool = True


def previous_period(f: BoardFilter) -> Tuple[date, date]:
    if f.compare == "anio_anterior":
        return _minus_year(f.date_from), _minus_year(f.date_to)
    length = (f.date_to - f.date_from).days + 1
    prev_to = f.date_from - timedelta(days=1)
    return prev_to - timedelta(days=length - 1), prev_to


def _minus_year(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # 29 Feb -> 28 Feb
        return day.replace(year=day.year - 1, day=28)


# ── Universe ─────────────────────────────────────────────────────


@dataclass
class Pub:
    mla: str
    store_id: Optional[int] = None
    status: Optional[str] = None
    listing_type: Optional[str] = None
    is_catalog: bool = False
    is_full: bool = False
    title: Optional[str] = None
    started_at: Optional[datetime] = None

    @property
    def store_bucket(self) -> str:
        return str(self.store_id) if self.store_id is not None else NO_STORE

    def types(self) -> Set[str]:
        types = set()
        if self.listing_type in ("clasica", "premium"):
            types.add(self.listing_type)
        if self.is_catalog:
            types.add("catalogo")
        if self.is_full:
            types.add("full")
        return types


@dataclass
class PairAgg:
    """Everything the board needs about one (product, MLA) pair."""

    units: int = 0
    gross: Decimal = Decimal("0")
    tg: Decimal = Decimal("0")
    costo: Decimal = Decimal("0")
    prev_units: int = 0
    prev_gross: Decimal = Decimal("0")
    prev_tg: Decimal = Decimal("0")
    prev_costo: Decimal = Decimal("0")
    windows: Dict[str, int] = field(default_factory=lambda: {name: 0 for name, _ in WINDOWS})
    units_24h: int = 0
    # day -> [units, gross, tg, costo] over the 90d window and the period.
    daily: Dict[date, List] = field(default_factory=dict)
    last_sale_at: Optional[datetime] = None


def _load_pubs(db: Session) -> Tuple[Dict[str, Pub], Dict[str, int]]:
    """Every MLA the ERP mirror knows -> its publication record, and its
    product. One row per MLA (the newest `mlp_id` wins on duplicates)."""
    rows = (
        db.query(
            MercadoLibreItemPublicado.mlp_id,
            MercadoLibreItemPublicado.mlp_publicationID,
            MercadoLibreItemPublicado.item_id,
            MercadoLibreItemPublicado.mlp_official_store_id,
            MercadoLibreItemPublicado.mlp_lastStatusID,
            MercadoLibreItemPublicado.mlp_Active,
            MercadoLibreItemPublicado.mlp_listing_type_id,
            MercadoLibreItemPublicado.mlp_catalog_listing,
            MercadoLibreItemPublicado.mlp_is4FulFillment,
            MercadoLibreItemPublicado.mlp_itemTitle,
            MercadoLibreItemPublicado.mlp_start_time,
            MercadoLibreItemPublicado.mlp_creationDate,
        )
        .filter(MercadoLibreItemPublicado.mlp_publicationID.isnot(None))
        .order_by(MercadoLibreItemPublicado.mlp_id)
        .all()
    )
    pubs: Dict[str, Pub] = {}
    product_of: Dict[str, int] = {}
    for r in rows:
        pubs[r.mlp_publicationID] = Pub(
            mla=r.mlp_publicationID,
            store_id=r.mlp_official_store_id,
            status=resolve_publication_status(r.mlp_lastStatusID, r.mlp_Active),
            listing_type=LISTING_TYPES.get(r.mlp_listing_type_id or "", r.mlp_listing_type_id),
            is_catalog=bool(r.mlp_catalog_listing),
            is_full=bool(r.mlp_is4FulFillment),
            title=r.mlp_itemTitle,
            started_at=r.mlp_start_time or r.mlp_creationDate,
        )
        if r.item_id is not None:
            product_of[r.mlp_publicationID] = r.item_id
    return pubs, product_of


def _as_aware(moment: Optional[datetime]) -> Optional[datetime]:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _load_pairs(db: Session, f: BoardFilter) -> Tuple[Dict[Tuple[int, str], PairAgg], Dict[str, Pub]]:
    pubs, product_of = _load_pubs(db)
    pairs: Dict[Tuple[int, str], PairAgg] = {(product, mla): PairAgg() for mla, product in product_of.items()}

    prev_from, prev_to = previous_period(f)
    series_from = f.date_to - timedelta(days=SERIES_DAYS - 1)
    read_from = min(series_from, f.date_from)
    window_from = {name: f.date_to - timedelta(days=days - 1) for name, days in WINDOWS}

    rows = db.query(
        MlProductDailyMetrics.product_item_id,
        MlProductDailyMetrics.mla,
        MlProductDailyMetrics.day,
        MlProductDailyMetrics.units,
        MlProductDailyMetrics.gross_ars,
        MlProductDailyMetrics.total_gauss,
        MlProductDailyMetrics.costo,
    ).filter(
        or_(
            MlProductDailyMetrics.day.between(read_from, f.date_to),
            MlProductDailyMetrics.day.between(prev_from, prev_to),
        )
    )
    for r in rows:
        agg = pairs.setdefault((r.product_item_id, r.mla), PairAgg())
        units, gross, tg, costo = (
            r.units or 0,
            Decimal(r.gross_ars or 0),
            Decimal(r.total_gauss or 0),
            Decimal(r.costo or 0),
        )
        if prev_from <= r.day <= prev_to:
            agg.prev_units += units
            agg.prev_gross += gross
            agg.prev_tg += tg
            agg.prev_costo += costo
        if read_from <= r.day <= f.date_to:
            agg.daily[r.day] = [units, gross, tg, costo]
            if r.day >= f.date_from:
                agg.units += units
                agg.gross += gross
                agg.tg += tg
                agg.costo += costo
            for name, start in window_from.items():
                if r.day >= start:
                    agg.windows[name] += units

    last_sales = db.query(
        MlProductDailyMetrics.product_item_id, MlProductDailyMetrics.mla, func.max(MlProductDailyMetrics.last_sale_at)
    ).group_by(MlProductDailyMetrics.product_item_id, MlProductDailyMetrics.mla)
    for product, mla, last in last_sales:
        if (product, mla) in pairs:
            pairs[(product, mla)].last_sale_at = _as_aware(last)

    for (product, mla), units in _units_last_24h(db).items():
        if (product, mla) in pairs:
            pairs[(product, mla)].units_24h = units
    return pairs, pubs


def _units_last_24h(db: Session) -> Dict[Tuple[int, str], int]:
    """Rolling 24h, from the orders themselves: the daily rollup has no
    hours. Same day rule (the group's accreditation) and the same exclusion
    of a cancellation ML did not cover."""
    since = now_utc() - timedelta(hours=24)
    # ponytail: `ml_group_metrics.group_date` has no index; a ~77k-row scan is
    # cheap today -- add one if this shows up in a slow-query log.
    groups = db.query(MlGroupMetrics.member_order_ids).filter(MlGroupMetrics.group_date >= since).all()
    order_ids = sorted({int(oid) for (members,) in groups for oid in (members or ())})
    if not order_ids:
        return {}
    rows = (
        db.query(MlOrderItemOps.item_id, MlOrderItemOps.quantity, MlOrderItemCosto.producto_item_id)
        .join(MlOrdersOps, MlOrdersOps.order_id == MlOrderItemOps.order_id)
        .outerjoin(
            MlOrderItemCosto,
            (MlOrderItemCosto.order_id == MlOrderItemOps.order_id)
            & (MlOrderItemCosto.item_id == MlOrderItemOps.item_id),
        )
        .filter(
            MlOrderItemOps.order_id.in_(order_ids),
            or_(MlOrdersOps.status != "cancelled", MlOrdersOps.covered_by_marketplace.is_(True)),
        )
    )
    units: Dict[Tuple[int, str], int] = defaultdict(int)
    for mla, quantity, product in rows:
        units[(product if product is not None else NO_PRODUCT, mla)] += quantity or 0
    return units


# ── Rows ─────────────────────────────────────────────────────────


@dataclass
class Row:
    key: str
    product_item_id: int
    mla: Optional[str]
    pairs: List[Tuple[int, str]]
    title: str
    sku: Optional[str] = None
    marca: Optional[str] = None
    publications_count: int = 0
    units: int = 0
    gross: Decimal = Decimal("0")
    tg: Decimal = Decimal("0")
    costo: Decimal = Decimal("0")
    prev_tg: Decimal = Decimal("0")
    prev_costo: Decimal = Decimal("0")
    windows: Dict[str, int] = field(default_factory=dict)
    units_24h: int = 0
    last_sale_at: Optional[datetime] = None
    ageing_days: Optional[int] = None
    pub: Optional[Pub] = None

    @property
    def markup(self) -> Optional[Decimal]:
        return markup_of(self.tg, self.costo)

    @property
    def markup_prev(self) -> Optional[Decimal]:
        return markup_of(self.prev_tg, self.prev_costo)

    @property
    def markup_delta(self) -> Optional[Decimal]:
        if self.markup is None or self.markup_prev is None:
            return None
        return self.markup - self.markup_prev

    def alerts(self) -> Set[str]:
        flags = set()
        if self.windows.get("30d", 0) == 0:
            flags.add("sin_ventas_30d")
        if self.ageing_days is not None and self.ageing_days > AGEING_ALERT_DAYS:
            flags.add("ageing_60d")
        if self.markup_delta is not None and self.markup_delta <= FALLING_MARGIN_PP:
            flags.add("margen_cayendo")
        return flags


def markup_of(tg: Decimal, costo: Decimal) -> Optional[Decimal]:
    if not costo:
        return None
    return tg / costo * Decimal("100")


@dataclass
class Universe:
    pairs: Dict[Tuple[int, str], PairAgg]
    pubs: Dict[str, Pub]
    products: Dict[int, ProductoERP]
    pm_pairs: Optional[List[Tuple[str, str]]]


def load_universe(db: Session, f: BoardFilter) -> Universe:
    pairs, pubs = _load_pairs(db, f)
    product_ids = sorted({product for product, _mla in pairs if product != NO_PRODUCT})
    products: Dict[int, ProductoERP] = {}
    for start in range(0, len(product_ids), 5000):
        chunk = product_ids[start : start + 5000]
        for p in db.query(ProductoERP).filter(ProductoERP.item_id.in_(chunk)):
            products[p.item_id] = p
    pm_pairs = _resolve_pm_pairs(db, f.pms) if f.pms else None
    return Universe(pairs=pairs, pubs=pubs, products=products, pm_pairs=pm_pairs)


def _pair_passes(u: Universe, f: BoardFilter, pair: Tuple[int, str], skip: str = "") -> bool:
    product_id, mla = pair
    pub = u.pubs.get(mla) or Pub(mla=mla)
    product = u.products.get(product_id)
    if f.stores and skip != "stores" and pub.store_bucket not in f.stores:
        return False
    if f.pub_status and skip != "pub_status" and pub.status not in f.pub_status:
        return False
    if f.pub_type and skip != "pub_type" and not (pub.types() & set(f.pub_type)):
        return False
    if f.marcas and (product is None or (product.marca or "").upper() not in {m.upper() for m in f.marcas}):
        return False
    if f.subcategorias and (product is None or product.subcategoria_id not in f.subcategorias):
        return False
    if u.pm_pairs is not None:
        if product is None or ((product.marca or "").upper(), (product.categoria or "").upper()) not in set(u.pm_pairs):
            return False
    if f.q:
        needle = f.q.strip().lower()
        haystack = [mla, pub.title or ""]
        if product is not None:
            haystack += [product.descripcion or "", product.codigo or "", product.marca or ""]
        if not any(needle in (text or "").lower() for text in haystack):
            return False
    return True


def _ageing(today: date, last_sale_at: Optional[datetime], started: Iterable[Optional[datetime]]) -> Optional[int]:
    if last_sale_at is not None:
        return (today - business_day(last_sale_at)).days
    # The ERP mirror's datetimes are naive LOCAL (business) times, unlike the
    # rollup's tz-aware `last_sale_at`: read their calendar day as-is.
    starts = [s.date() if s.tzinfo is None else business_day(s) for s in started if s is not None]
    if not starts:
        return None
    return (today - min(starts)).days


def build_rows(u: Universe, f: BoardFilter, skip: str = "") -> List[Row]:
    """Rows of the current grouping, from the pairs that pass every filter
    but `skip` (a facet's own axis). Alerts are applied here too, unless
    skipped."""
    today = today_business()
    grouped: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for pair in u.pairs:
        if _pair_passes(u, f, pair, skip):
            key = str(pair[0]) if f.group_by == "product" else pair[1]
            grouped[key].append(pair)

    rows: List[Row] = []
    for key, pairs in grouped.items():
        product_id = pairs[0][0] if f.group_by == "product" else _main_product(u, pairs)
        mla = None if f.group_by == "product" else key
        product = u.products.get(product_id)
        pub = u.pubs.get(mla) if mla else None
        title = (product.descripcion if product else None) or (pub.title if pub else None) or "Sin producto"
        row = Row(
            key=key,
            product_item_id=product_id,
            mla=mla,
            pairs=sorted(pairs),
            title=title,
            sku=product.codigo if product else None,
            marca=product.marca if product else None,
            publications_count=len({m for _p, m in pairs}),
            windows={name: 0 for name, _ in WINDOWS},
            pub=pub,
        )
        for pair in pairs:
            agg = u.pairs[pair]
            row.units += agg.units
            row.gross += agg.gross
            row.tg += agg.tg
            row.costo += agg.costo
            row.prev_tg += agg.prev_tg
            row.prev_costo += agg.prev_costo
            row.units_24h += agg.units_24h
            for name in row.windows:
                row.windows[name] += agg.windows[name]
            if agg.last_sale_at is not None and (row.last_sale_at is None or agg.last_sale_at > row.last_sale_at):
                row.last_sale_at = agg.last_sale_at
        row.ageing_days = _ageing(
            today, row.last_sale_at, ((u.pubs.get(m) or Pub(mla=m)).started_at for _p, m in pairs)
        )
        if f.alerts and skip != "alerts" and not (row.alerts() & set(f.alerts)):
            continue
        rows.append(row)
    return rows


def _main_product(u: Universe, pairs: Sequence[Tuple[int, str]]) -> int:
    """A publication row's product: the one that sold the most units in the
    period (a publication relinked to another product keeps both pairs)."""
    return max(pairs, key=lambda pair: (u.pairs[pair].units, pair[0] != NO_PRODUCT, -pair[0]))[0]


def sort_rows(rows: List[Row], f: BoardFilter) -> List[Row]:
    def value(row: Row):
        return {
            "gross": row.gross,
            "units": row.units,
            "units_24h": row.units_24h,
            "total_gauss": row.tg,
            "markup": row.markup,
            "markup_delta": row.markup_delta,
            "last_sale": row.last_sale_at,
            "ageing": row.ageing_days,
            "title": row.title.lower(),
        }.get(f.sort, row.windows.get(f.sort.removeprefix("units_")))

    present = [r for r in rows if value(r) is not None]
    missing = [r for r in rows if value(r) is None]
    present.sort(key=lambda r: r.key)
    present.sort(key=value, reverse=f.sort_desc)
    missing.sort(key=lambda r: r.key)
    # None always last, whatever the direction: "no markup" is not "lowest".
    return present + missing


def series_for(u: Universe, row: Row, f: BoardFilter) -> Tuple[List[int], List[Optional[float]]]:
    """Daily units and daily markup over the 90 days ending on `date_to`."""
    start = f.date_to - timedelta(days=SERIES_DAYS - 1)
    units = [0] * SERIES_DAYS
    tg = [Decimal("0")] * SERIES_DAYS
    costo = [Decimal("0")] * SERIES_DAYS
    for pair in row.pairs:
        for day, (d_units, _gross, d_tg, d_costo) in u.pairs[pair].daily.items():
            index = (day - start).days
            if 0 <= index < SERIES_DAYS:
                units[index] += d_units
                tg[index] += d_tg
                costo[index] += d_costo
    markups = [_round(markup_of(tg[i], costo[i])) for i in range(SERIES_DAYS)]
    return units, markups


def period_series(u: Universe, rows: Sequence[Row], f: BoardFilter, start: date, end: date) -> Dict[str, list]:
    """Per-day totals of `rows` between `start` and `end` (KPI sparklines)."""
    days = (end - start).days + 1
    units = [0] * days
    gross = [Decimal("0")] * days
    tg = [Decimal("0")] * days
    costo = [Decimal("0")] * days
    for row in rows:
        for pair in row.pairs:
            for day, (d_units, d_gross, d_tg, d_costo) in u.pairs[pair].daily.items():
                index = (day - start).days
                if 0 <= index < days:
                    units[index] += d_units
                    gross[index] += d_gross
                    tg[index] += d_tg
                    costo[index] += d_costo
    return {
        "units": units,
        "gross": [float(v) for v in gross],
        "total_gauss": [float(v) for v in tg],
        "markup": [_round(markup_of(tg[i], costo[i])) for i in range(days)],
    }


def _round(value: Optional[Decimal]) -> Optional[float]:
    return None if value is None else round(float(value), 1)


def refreshed_at(db: Session) -> Optional[datetime]:
    return _as_aware(db.query(func.max(MlProductDailyMetrics.updated_at)).scalar())
