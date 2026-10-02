"""The Métricas ML board (ODD `metricas-ml-tablero` T3/T5): one row per
PRODUCT (or per PUBLICATION), with sales windows, markup now vs before,
90-day daily series for the sparklines, last sale and ageing.

Everything is aggregated, filtered, sorted and PAGED in SQL; Python only
shapes the page it gets back.

WHERE THE NUMBERS COME FROM: the tables we already have, never a derived
summary table (ODD "Sin tabla resumen"). `sales.sale_lines` is the ONE
per-sold-item base (accreditation day, frozen-cost product, cancellation
and money rules -- the Ventas ML ones); every window, markup, series, last
sale and ageing is read from it, so 24h <= 3d <= 7d <= 15d <= 30d holds by
construction.

HOW A REQUEST RUNS (`with Board(db, f) as b:` -- see `__enter__`):

1. `__enter__` opens a SAVEPOINT inside the request's transaction and
   materializes, `ON COMMIT DROP` on Postgres, two TEMPORARY tables, each
   `ANALYZE`d (a fresh temp table has no statistics and the planner would
   nest loops over it):
   - `LINES_TABLE`: the base summed per (product, MLA, business day) over
     the days the request reads (period, comparison period, the 90-day
     series) plus the rolling 24h -- ONE pass, through the group-date index;
   - `PAIRS_TABLE`: per (product, MLA) pair, the period, the comparison
     period, the 3/7/15/30-day windows and the 24h, summed from the lines;
     the last sale EVER (`sales.last_sales`, all history); and the pair's
     publication data (newest `mlp_id` wins) and product data, joined --
     never loaded whole into Python. The universe: every publication the
     ERP mirror knows plus every pair ever sold.
2. Every statement after that reads the small temp tables: the KPI totals
   and their daily series, the chip counts (MATERIALIZED CTEs, each with its
   own axis cleared), the page (`ORDER BY` + `LIMIT/OFFSET`), and the page's
   pair details and 90-day series -- ONE bulk statement each, never one per
   row.
3. `__exit__` rolls the savepoint back: both CREATEs go with it.

A fixed number of statements per board request whatever the page size or
the volume, pinned with the measured timings by
`tests/services/ml_daily_metrics/test_board_volume_postgres.py`. With
`product_item_id` (a product's publication sub-rows) both tables hold only
that product's groups, reached through the frozen-cost product index: the
cost does not depend on how many other products sold.

WHY ONE TRANSACTION: production reaches Postgres through PgBouncer in
TRANSACTION pooling (`app/core/database.py`), so a server connection is ours
only for one transaction. The temp tables must never outlive it (the next
client on that server connection would inherit them) nor be needed after a
commit (later statements may run on another server connection). Hence the
savepoint that is always rolled back, `ON COMMIT DROP` as a second net, and
`Board` refusing loudly if something commits in the middle.

Markup is ALWAYS `SUM(total_gauss) / SUM(costo) x 100` over the selected
rows/days (the per-group all-or-nothing population, `mtg`/`costo`), never an
average of percentages; no cost means no markup (NULL), never 0. The store is the publication's CURRENT `mlp_official_store_id`
(decision in the ODD doc): a publication that moved store takes its history
with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import (
    Date,
    String,
    and_,
    case,
    cast,
    false,
    func,
    literal,
    or_,
    column,
    select,
    table,
    text,
    union,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import ClauseElement, Executable

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_orders_ops import MlOpsSyncCursor
from app.models.producto import ProductoERP
from app.services.ml_daily_metrics.sales import (
    BUSINESS_TZ,
    NO_PRODUCT,
    business_date,
    day_bounds,
    last_sales,
    sale_lines,
)
from app.services.ml_publication_status_service import ML_PUBLICATION_STATUS_MAP
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
AGEING_OK_DAYS = 30
# "Margen cayendo": the period's markup is at least this many points below the
# comparison period's (decision recorded in the ODD doc).
FALLING_MARGIN_PP = -1
LISTING_TYPES = {"gold_special": "clasica", "gold_pro": "premium"}

# The request's materialized (product, MLA) aggregate: computed once per
# request, read by every statement after it. Production reaches Postgres
# through PgBouncer in TRANSACTION pooling (`app/core/database.py`): a server
# connection is ours only for one transaction. So the table lives and dies
# INSIDE one transaction -- created `ON COMMIT DROP`, inside a SAVEPOINT that
# `Board.__exit__` always rolls back (a rolled-back CREATE leaves nothing
# behind, success or failure), and a commit in between is refused loudly.
PAIRS_TABLE = "board_pair_agg"
LINES_TABLE = "board_lines"
# The cursors whose completed passes keep the sales fresh (same as Ventas ML's
# sync-status): the windowed sweep and the event-driven activity drain.
FRESHNESS_CURSORS = ("sweep", "ml_activity")


class CreateTempTableAs(Executable, ClauseElement):
    """`CREATE TEMPORARY TABLE <name> [ON COMMIT DROP] AS <select>`, compiled
    by the dialect (bind parameters included). `ON COMMIT DROP` on Postgres
    only: SQLite has no such clause (and no connection pooler to leak to)."""

    inherit_cache = False

    def __init__(self, name: str, query: Any) -> None:
        self.name = name
        self.query = query


@compiles(CreateTempTableAs)
def _compile_create_temp_table_as(element: CreateTempTableAs, compiler: Any, **kw: Any) -> str:
    on_commit = " ON COMMIT DROP" if compiler.dialect.name == "postgresql" else ""
    return f"CREATE TEMPORARY TABLE {element.name}{on_commit} AS {compiler.process(element.query, **kw)}"


M = MercadoLibreItemPublicado
P = ProductoERP


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
    # Exclusion mirrors inclusion ("hide these"): a pair is dropped when it
    # matches ANY excluded value. Like their include twins, each facet ignores
    # its own axis' exclusion, so a chip keeps showing what it is hiding.
    pub_status_exclude: Tuple[str, ...] = ()
    pub_type_exclude: Tuple[str, ...] = ()
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


def markup_of(tg: Optional[Decimal], costo: Optional[Decimal]) -> Optional[Decimal]:
    if not costo or tg is None:
        return None
    return Decimal(tg) / Decimal(costo) * Decimal("100")


def _as_date(value: Any) -> Optional[date]:
    """SQLite hands dates back as text; Postgres as `date`."""
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _as_datetime(value: Any) -> Optional[datetime]:
    """SQLite hands a timestamp read through an untyped temp-table column
    back as text; Postgres as `datetime`."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _as_aware(moment: Optional[datetime]) -> Optional[datetime]:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


# ── Result shapes ────────────────────────────────────────────────


@dataclass
class Pub:
    mla: str
    store_id: Optional[int] = None
    status: Optional[str] = None
    listing_type: Optional[str] = None
    is_catalog: bool = False
    is_full: bool = False
    title: Optional[str] = None
    thumbnail: Optional[str] = None


@dataclass
class Row:
    key: str
    product_item_id: int
    mla: Optional[str]
    title: str = ""
    sku: Optional[str] = None
    marca: Optional[str] = None
    publications_count: int = 0
    units: int = 0
    gross: Decimal = Decimal("0")
    # `tg`: every known Total Gauss (what "Total Gauss" shows). `mtg`/`costo`:
    # the markup's numerator/denominator (per-group all-or-nothing).
    tg: Decimal = Decimal("0")
    mtg: Decimal = Decimal("0")
    costo: Decimal = Decimal("0")
    prev_tg: Decimal = Decimal("0")
    prev_mtg: Decimal = Decimal("0")
    prev_costo: Decimal = Decimal("0")
    windows: Dict[str, int] = field(default_factory=dict)
    units_24h: int = 0
    last_sale_at: Optional[datetime] = None
    ageing_days: Optional[int] = None
    pub: Optional[Pub] = None
    thumbnail: Optional[str] = None
    flags: Set[str] = field(default_factory=set)
    series_units: List[int] = field(default_factory=list)
    series_markup: List[Optional[float]] = field(default_factory=list)

    @property
    def markup(self) -> Optional[Decimal]:
        return markup_of(self.mtg, self.costo)

    @property
    def markup_prev(self) -> Optional[Decimal]:
        return markup_of(self.prev_mtg, self.prev_costo)

    @property
    def markup_delta(self) -> Optional[Decimal]:
        if self.markup is None or self.markup_prev is None:
            return None
        return self.markup - self.markup_prev

    def alerts(self) -> Set[str]:
        return set(self.flags)


@dataclass
class Kpis:
    units: int
    gross: Decimal
    tg: Decimal
    mtg: Decimal
    costo: Decimal
    prev_units: int
    prev_gross: Decimal
    prev_tg: Decimal
    prev_mtg: Decimal
    prev_costo: Decimal
    rows: int
    with_sales: int
    ageing_avg: Optional[float]
    up_to_30: int
    from_31_to_60: int
    over_60: int
    series_units: List[int]
    series_gross: List[float]
    series_tg: List[float]
    series_markup: List[Optional[float]]


@dataclass
class Facets:
    stores: Dict[str, int]
    stores_total: int
    pub_status: Dict[str, int]
    pub_type: Dict[str, int]
    alerts: Dict[str, int]


def _round1(value: Optional[Decimal]) -> Optional[float]:
    return None if value is None else round(float(value), 1)


# ── The query builder ────────────────────────────────────────────


class Board:
    """One request's worth of board SQL. Construct once per request (it
    fixes the clock and resolves the PM pairs up front, once)."""

    def __init__(self, db: Session, f: BoardFilter, product_item_id: Optional[int] = None):
        self.db = db
        self.f = f
        self.product_item_id = product_item_id
        self.sqlite = db.get_bind().dialect.name == "sqlite"
        self.now = now_utc()
        self.today = self.now.astimezone(BUSINESS_TZ).date()
        self.prev_from, self.prev_to = previous_period(f)
        self.window_from = {name: f.date_to - timedelta(days=days - 1) for name, days in WINDOWS}
        self.series_from = f.date_to - timedelta(days=SERIES_DAYS - 1)
        self.since_24h = self.now - timedelta(hours=24)
        self.pm_pairs = _resolve_pm_pairs(db, f.pms) if f.pms else None

    # ── dialect helpers ──

    def _date_of(self, expr):
        # The ERP mirror's datetimes are naive LOCAL (business) times: their
        # calendar day is read as-is.
        return func.date(expr) if self.sqlite else cast(expr, Date)

    def _days_since(self, day_expr):
        if self.sqlite:
            return func.julianday(literal(self.today.isoformat())) - func.julianday(day_expr)
        return literal(self.today, Date) - day_expr

    def _day(self, value: date):
        return literal(value, Date)

    # ── building blocks ──

    def _pub(self, mlas: Any = None):
        """Each MLA's current publication row (newest `mlp_id`), with its
        status/type/store resolved in SQL. `mlas` (a one-column select)
        narrows it to those MLAs: a product's sub-rows never read every
        publication."""
        latest = select(func.max(M.mlp_id)).where(M.mlp_publicationID.isnot(None))
        if mlas is not None:
            latest = latest.where(M.mlp_publicationID.in_(mlas))
        latest = latest.group_by(M.mlp_publicationID)
        status = case(
            *((M.mlp_lastStatusID == sid, literal(name)) for sid, name in ML_PUBLICATION_STATUS_MAP.items()),
            (
                and_(M.mlp_lastStatusID.isnot(None), M.mlp_lastStatusID != 0),
                literal("status_") + cast(M.mlp_lastStatusID, String),
            ),
            (M.mlp_Active.is_(True), literal("active")),
            (M.mlp_Active.is_(False), literal("paused")),
            else_=None,
        )
        listing = case(
            *((M.mlp_listing_type_id == raw, literal(name)) for raw, name in LISTING_TYPES.items()),
            else_=M.mlp_listing_type_id,
        )
        return (
            select(
                M.mlp_publicationID.label("mla"),
                M.item_id.label("item_id"),
                M.mlp_official_store_id.label("store_id"),
                status.label("status"),
                listing.label("listing_type"),
                func.coalesce(M.mlp_catalog_listing, false()).label("is_catalog"),
                func.coalesce(M.mlp_is4FulFillment, false()).label("is_full"),
                M.mlp_itemTitle.label("title"),
                M.mlp_thumbnail.label("thumbnail"),
                self._date_of(func.coalesce(M.mlp_start_time, M.mlp_creationDate)).label("start_day"),
            )
            .where(M.mlp_id.in_(latest), *([M.mlp_publicationID.in_(mlas)] if mlas is not None else []))
            .subquery("pub")
        )

    def _ranges(self):
        """The accreditation timestamps the request reads, as UTC ranges: the
        period through `date_to` and its 30-day windows and 90-day series,
        the comparison period, and the rolling 24h."""
        f = self.f
        first = min(f.date_from, self.window_from["30d"], self.series_from)
        return [day_bounds(first, f.date_to), day_bounds(self.prev_from, self.prev_to), (self.since_24h, None)]

    def _lines_source(self):
        """The base summed per (product, MLA, business day) over `_ranges`:
        what every period/window total, the KPI series and the 90-day
        sparklines read. `u24` is the part accredited in the last 24h -- a
        SUBSET of the day's units by construction."""
        lines = sale_lines(sqlite=self.sqlite, ranges=self._ranges(), product=self.product_item_id)
        return select(
            lines.c.product,
            lines.c.mla,
            lines.c.day,
            func.sum(lines.c.qty).label("units"),
            func.sum(lines.c.gross).label("gross"),
            func.sum(lines.c.tg).label("tg"),
            func.sum(lines.c.mtg).label("mtg"),
            func.sum(lines.c.mcosto).label("mcosto"),
            func.sum(case((lines.c.group_date >= self.since_24h, lines.c.qty), else_=0)).label("u24"),
            func.max(lines.c.group_date).label("last_at"),
        ).group_by(lines.c.product, lines.c.mla, lines.c.day)

    def _agg(self):
        """ONE pass over the request's lines, per (product, MLA): the period,
        the comparison period, the 3/7/15/30-day windows and the 24h."""
        f, L = self.f, self.lines

        def total(col, start: date, end: date):
            return func.coalesce(func.sum(case((L.c.day.between(self._day(start), self._day(end)), col), else_=0)), 0)

        cols = [
            L.c.product.label("product"),
            L.c.mla.label("mla"),
            total(L.c.units, f.date_from, f.date_to).label("units"),
            total(L.c.gross, f.date_from, f.date_to).label("gross"),
            total(L.c.tg, f.date_from, f.date_to).label("tg"),
            total(L.c.mtg, f.date_from, f.date_to).label("mtg"),
            total(L.c.mcosto, f.date_from, f.date_to).label("costo"),
            total(L.c.units, self.prev_from, self.prev_to).label("prev_units"),
            total(L.c.gross, self.prev_from, self.prev_to).label("prev_gross"),
            total(L.c.tg, self.prev_from, self.prev_to).label("prev_tg"),
            total(L.c.mtg, self.prev_from, self.prev_to).label("prev_mtg"),
            total(L.c.mcosto, self.prev_from, self.prev_to).label("prev_costo"),
            *(total(L.c.units, start, f.date_to).label(f"w{name}") for name, start in self.window_from.items()),
            func.coalesce(func.sum(L.c.u24), 0).label("u24"),
        ]
        return select(*cols).group_by(L.c.product, L.c.mla).subquery("agg")

    def _pair_source(self):
        """Every (product, MLA) pair of the universe with its aggregates, its
        last sale ever and its publication/product attributes -- what gets
        materialized once."""
        agg = self._agg()
        last = last_sales(sqlite=self.sqlite, product=self.product_item_id).cte("last_sale")
        published = select(M.item_id, M.mlp_publicationID).where(M.item_id.isnot(None), M.mlp_publicationID.isnot(None))
        if self.product_item_id is not None:
            published = published.where(M.item_id == self.product_item_id)
        pairs = union(select(last.c.product, last.c.mla), published).subquery("pairs")
        pub = self._pub(select(pairs.c.mla) if self.product_item_id is not None else None)
        sums = [c for c in agg.c.keys() if c not in ("product", "mla")]
        return (
            select(
                pairs.c.product.label("product"),
                pairs.c.mla.label("mla"),
                pub.c.item_id.label("pub_item_id"),
                pub.c.store_id,
                pub.c.status,
                pub.c.listing_type,
                pub.c.is_catalog,
                pub.c.is_full,
                pub.c.start_day,
                pub.c.title.label("pub_title"),
                pub.c.thumbnail,
                P.descripcion,
                P.codigo,
                P.marca,
                P.categoria,
                P.subcategoria_id,
                *(func.coalesce(agg.c[name], 0).label(name) for name in sums),
                last.c.last_at,
                business_date(last.c.last_at, self.sqlite).label("last_day"),
            )
            .select_from(pairs)
            .outerjoin(pub, pub.c.mla == pairs.c.mla)
            .outerjoin(P, P.item_id == pairs.c.product)
            .outerjoin(agg, and_(agg.c.product == pairs.c.product, agg.c.mla == pairs.c.mla))
            .outerjoin(last, and_(last.c.product == pairs.c.product, last.c.mla == pairs.c.mla))
        )

    # ── request lifecycle: the lines and the pair aggregate, computed ONCE ──

    def _materialize(self, name: str, source: Any, types: Optional[Dict[str, Any]] = None) -> Any:
        self.db.execute(CreateTempTableAs(name, source))
        if not self.sqlite:
            # A fresh temp table has no statistics: without them the planner
            # guesses tiny row counts and nests loops over it (seen: 0.7 s
            # for one chip count). Analyzing a narrow temp table is ms.
            self.db.execute(text(f"ANALYZE {name}"))
        types = types or {}
        return table(name, *(column(c, types.get(c)) for c in source.selected_columns.keys()))

    def __enter__(self) -> "Board":
        # Everything below runs in ONE transaction: a SAVEPOINT inside the
        # request's transaction, rolled back on the way out whatever happens.
        self._savepoint = self.db.begin_nested()
        if not self.db.in_transaction() or not self._savepoint.is_active:
            raise RuntimeError("Board needs an open transaction: its temp tables must not outlive it")
        self.lines = self._materialize(LINES_TABLE, self._lines_source(), {"day": Date()})
        self.t = self._materialize(PAIRS_TABLE, self._pair_source())
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if not self._savepoint.is_active:
            # Someone committed (or rolled back) the transaction in the middle
            # of the board: under transaction pooling the rest may have run on
            # another server connection. A bug, never a state to paper over.
            if exc_type is None:
                raise RuntimeError("The board's transaction ended midway (commit/rollback inside Board)")
            return
        # Read-only: roll back. The CREATE goes with it -- nothing survives,
        # and a failed statement's aborted transaction is usable again, so the
        # caller sees the ORIGINAL error, not a cleanup one.
        self._savepoint.rollback()

    def filtered_pairs(self, skip: str = ""):
        """One row per (product, MLA) pair that passes every filter but
        `skip`, read from the request's materialized pair table."""
        f, t = self.f, self.t
        rk = cast(t.c.product, String) if f.group_by == "product" else t.c.mla
        q = select(
            rk.label("rk"),
            *(t.c[name] for name in t.c.keys()),
            func.coalesce(t.c.descripcion, t.c.pub_title).label("title"),
        )
        conditions = []
        if f.stores and skip != "stores":
            ids = [int(s) for s in f.stores if s != NO_STORE]
            store_match = [t.c.store_id.in_(ids)] if ids else []
            if NO_STORE in f.stores:
                store_match.append(t.c.store_id.is_(None))
            conditions.append(or_(*store_match))
        if f.pub_status and skip != "pub_status":
            conditions.append(t.c.status.in_(f.pub_status))
        if f.pub_type and skip != "pub_type":
            types = []
            listing = [x for x in f.pub_type if x in ("clasica", "premium")]
            if listing:
                types.append(t.c.listing_type.in_(listing))
            if "catalogo" in f.pub_type:
                types.append(t.c.is_catalog == True)  # noqa: E712 -- untyped temp-table column
            if "full" in f.pub_type:
                types.append(t.c.is_full == True)  # noqa: E712
            conditions.append(or_(*types))
        if f.pub_status_exclude and skip != "pub_status":
            # A pair with no known status is not "paused": keep it.
            conditions.append(or_(t.c.status.is_(None), t.c.status.notin_(f.pub_status_exclude)))
        if f.pub_type_exclude and skip != "pub_type":
            hidden = [x for x in f.pub_type_exclude if x in ("clasica", "premium")]
            if hidden:
                conditions.append(or_(t.c.listing_type.is_(None), t.c.listing_type.notin_(hidden)))
            if "catalogo" in f.pub_type_exclude:
                conditions.append(t.c.is_catalog.isnot(True))
            if "full" in f.pub_type_exclude:
                conditions.append(t.c.is_full.isnot(True))
        if f.marcas:
            conditions.append(func.upper(t.c.marca).in_([m.upper() for m in f.marcas]))
        if f.subcategorias:
            conditions.append(t.c.subcategoria_id.in_(f.subcategorias))
        if self.pm_pairs is not None:
            conditions.append(
                or_(
                    *(
                        and_(func.upper(t.c.marca) == marca, func.upper(t.c.categoria) == categoria)
                        for marca, categoria in self.pm_pairs
                    )
                )
                if self.pm_pairs
                else false()
            )
        if f.q:
            needle = f.q.strip().lower()
            conditions.append(
                or_(
                    *(
                        func.lower(func.coalesce(col, "")).contains(needle, autoescape=True)
                        for col in (t.c.mla, t.c.pub_title, t.c.descripcion, t.c.codigo, t.c.marca)
                    )
                )
            )
        if self.product_item_id is not None:
            conditions.append(t.c.product == self.product_item_id)
        if conditions:
            q = q.where(*conditions)
        return q.subquery("fp")

    def rows(self, skip: str = "", apply_alerts: bool = True):
        """One row per board row (product or MLA), with the derived markup,
        ageing reference day and alert flags, filtered by the alerts unless
        skipped. A subquery: callers page, count or aggregate it."""
        fp = self.filtered_pairs(skip)
        product = fp.c.product if self.f.group_by == "product" else fp.c.pub_item_id
        g = (
            select(
                fp.c.rk,
                (
                    func.max(fp.c.product)
                    if self.f.group_by == "product"
                    else func.coalesce(func.max(product), func.max(fp.c.product))
                ).label("product"),
                func.max(fp.c.title).label("title"),
                func.count(func.distinct(fp.c.mla)).label("pubs"),
                *(
                    func.sum(fp.c[name]).label(name)
                    for name in (
                        "units",
                        "gross",
                        "tg",
                        "mtg",
                        "costo",
                        "prev_units",
                        "prev_gross",
                        "prev_tg",
                        "prev_mtg",
                        "prev_costo",
                        "w3d",
                        "w7d",
                        "w15d",
                        "w30d",
                        "u24",
                    )
                ),
                func.max(fp.c.last_day).label("last_day"),
                func.max(fp.c.last_at).label("last_at"),
                func.min(fp.c.start_day).label("start_day"),
            )
            .group_by(fp.c.rk)
            .subquery("g")
        )
        markup = case((g.c.costo > 0, g.c.mtg * 100 / g.c.costo), else_=None)
        markup_prev = case((g.c.prev_costo > 0, g.c.prev_mtg * 100 / g.c.prev_costo), else_=None)
        delta = markup - markup_prev
        ref_day = func.coalesce(g.c.last_day, g.c.start_day)
        sin_ventas = g.c.w30d == 0
        ageing_60 = ref_day < self._day(self.today - timedelta(days=AGEING_ALERT_DAYS))
        cayendo = delta <= FALLING_MARGIN_PP
        q = select(
            *g.c,
            markup.label("markup"),
            markup_prev.label("markup_prev"),
            delta.label("markup_delta"),
            ref_day.label("ref_day"),
            case((sin_ventas, 1), else_=0).label("a_sin_ventas_30d"),
            case((ageing_60, 1), else_=0).label("a_ageing_60d"),
            case((cayendo, 1), else_=0).label("a_margen_cayendo"),
        )
        if apply_alerts and self.f.alerts and skip != "alerts":
            by_name = {"sin_ventas_30d": sin_ventas, "ageing_60d": ageing_60, "margen_cayendo": cayendo}
            q = q.where(or_(*(by_name[a] for a in self.f.alerts)))
        return q.subquery("board_rows")

    # ── statements ──

    def _ordered(self, rows: Any) -> Any:
        """The board's ORDER BY: the requested sort, then the unique row key.
        The key closes EVERY ordering: rows tie freely (gross 0, units 0...),
        and without a unique last term Postgres may order the ties
        differently in two LIMIT/OFFSET statements -- pages would repeat or
        skip rows."""
        sort_cols = {
            "gross": rows.c.gross,
            "units": rows.c.units,
            "units_24h": rows.c.u24,
            "units_3d": rows.c.w3d,
            "units_7d": rows.c.w7d,
            "units_15d": rows.c.w15d,
            "units_30d": rows.c.w30d,
            "total_gauss": rows.c.tg,
            "markup": rows.c.markup,
            "markup_delta": rows.c.markup_delta,
            "last_sale": rows.c.last_day,
            # More days of ageing = an OLDER reference day.
            "ageing": rows.c.ref_day,
            "title": func.lower(func.coalesce(rows.c.title, "")),
        }
        column = sort_cols[self.f.sort]
        descending = self.f.sort_desc if self.f.sort != "ageing" else not self.f.sort_desc
        return ((column.desc() if descending else column.asc()).nulls_last(), rows.c.rk.asc())

    def page(
        self, limit: Optional[int], offset: int = 0, apply_alerts: bool = True, with_series: bool = True
    ) -> List[Row]:
        rows = self.rows(apply_alerts=apply_alerts)
        q = select(rows).order_by(*self._ordered(rows))
        if limit is not None:
            q = q.limit(limit).offset(offset)
        return self._rows_of(q, with_series=with_series)

    def ordered_keys(self, limit: int) -> List[str]:
        """The keys of every row of the filtered board, in board order, at
        most `limit` of them: what a multi-transaction reader (the CSV export)
        fixes up front so a change between its pages can never repeat or drop
        a row."""
        rows = self.rows()
        q = select(rows.c.rk).order_by(*self._ordered(rows)).limit(limit)
        return [str(rk) for (rk,) in self.db.execute(q)]

    def rows_for_keys(self, keys: List[str], with_series: bool = False) -> List[Row]:
        """The rows of `keys`, in THAT order. A key no longer on the filtered
        board (its rows stopped matching the filters since the keys were
        taken) is skipped -- never replaced by another row."""
        if not keys:
            return []
        rows = self.rows()
        found = {row.key: row for row in self._rows_of(select(rows).where(rows.c.rk.in_(keys)), with_series)}
        return [found[key] for key in keys if key in found]

    def _rows_of(self, q: Any, with_series: bool) -> List[Row]:
        out = []
        for r in self.db.execute(q).mappings():
            ref_day = _as_date(r["ref_day"])
            row = Row(
                key=str(r["rk"]),
                product_item_id=int(r["product"]) if r["product"] is not None else NO_PRODUCT,
                mla=None if self.f.group_by == "product" else r["rk"],
                title=r["title"] or "Sin producto",
                publications_count=int(r["pubs"] or 0),
                units=int(r["units"] or 0),
                gross=Decimal(str(r["gross"] or 0)),
                tg=Decimal(str(r["tg"] or 0)),
                mtg=Decimal(str(r["mtg"] or 0)),
                costo=Decimal(str(r["costo"] or 0)),
                prev_tg=Decimal(str(r["prev_tg"] or 0)),
                prev_mtg=Decimal(str(r["prev_mtg"] or 0)),
                prev_costo=Decimal(str(r["prev_costo"] or 0)),
                last_sale_at=_as_aware(_as_datetime(r["last_at"])),
                windows={name: int(r[f"w{name}"] or 0) for name, _ in WINDOWS},
                units_24h=int(r["u24"] or 0),
                ageing_days=(self.today - ref_day).days if ref_day else None,
                flags={name for name in ALERTS if r[f"a_{name}"]},
            )
            out.append(row)
        self._decorate(out, with_series=with_series)
        return out

    def _on_page(self, fp: Any, by_key: Dict[str, Row]) -> Any:
        """The page's pairs, filtered on the RAW key column (an int product
        id or an MLA), never on the cast `rk`: the planner can estimate the
        former, and with a sound estimate it reaches the rollup through the
        (product, MLA, day) index instead of scanning it."""
        if self.f.group_by == "product":
            return fp.c.product.in_([int(key) for key in by_key])
        return fp.c.mla.in_(list(by_key))

    def _decorate(self, rows: List[Row], with_series: bool = True) -> None:
        """The page's pair details (publication data, product data, the last
        sale timestamp) and its 90-day series: TWO bulk statements for the
        whole page, never one per row."""
        if not rows:
            return
        by_key = {row.key: row for row in rows}
        fp = self.filtered_pairs()
        detail = select(
            fp.c.rk,
            fp.c.product,
            fp.c.mla,
            fp.c.units,
            fp.c.codigo,
            fp.c.marca,
            fp.c.descripcion,
            fp.c.store_id,
            fp.c.status,
            fp.c.listing_type,
            fp.c.is_catalog,
            fp.c.is_full,
            fp.c.pub_title.label("title"),
            fp.c.thumbnail,
        ).where(self._on_page(fp, by_key))
        pairs_of: Dict[str, List[Any]] = {}
        for d in self.db.execute(detail).mappings():
            pairs_of.setdefault(str(d["rk"]), []).append(d)
        for key, details in pairs_of.items():
            row = by_key[key]
            main = next((d for d in details if d["product"] == row.product_item_id and d["codigo"]), None)
            main = main or next((d for d in details if d["codigo"]), None)
            if main is not None:
                row.sku, row.marca = main["codigo"], main["marca"]
                if self.f.group_by == "product" and main["descripcion"]:
                    row.title = main["descripcion"]
            if row.mla is not None:
                own = next((d for d in details if d["mla"] == row.mla), details[0])
                row.pub = Pub(
                    mla=row.mla,
                    store_id=own["store_id"],
                    status=own["status"],
                    listing_type=own["listing_type"],
                    is_catalog=bool(own["is_catalog"]),
                    is_full=bool(own["is_full"]),
                    title=own["title"],
                    thumbnail=own["thumbnail"],
                )
                row.thumbnail = own["thumbnail"]
            else:
                ranked = sorted(details, key=lambda d: (-int(d["units"] or 0), d["mla"]))
                row.thumbnail = next((d["thumbnail"] for d in ranked if d["thumbnail"]), None)

        if not with_series:
            # Callers with no sparklines (the CSV export) skip the page's
            # most expensive read: the 90-day daily series.
            return
        L = self.lines
        series = (
            select(
                fp.c.rk,
                L.c.day,
                func.sum(L.c.units).label("units"),
                func.sum(L.c.mtg).label("tg"),
                func.sum(L.c.mcosto).label("costo"),
            )
            .select_from(fp)
            .join(L, and_(L.c.product == fp.c.product, L.c.mla == fp.c.mla))
            .where(
                self._on_page(fp, by_key),
                L.c.day.between(self._day(self.series_from), self._day(self.f.date_to)),
            )
            .group_by(fp.c.rk, L.c.day)
        )
        units = {key: [0] * SERIES_DAYS for key in by_key}
        tg = {key: [Decimal("0")] * SERIES_DAYS for key in by_key}
        costo = {key: [Decimal("0")] * SERIES_DAYS for key in by_key}
        for s in self.db.execute(series).mappings():
            key, index = str(s["rk"]), (_as_date(s["day"]) - self.series_from).days
            units[key][index] += int(s["units"] or 0)
            tg[key][index] += Decimal(str(s["tg"] or 0))
            costo[key][index] += Decimal(str(s["costo"] or 0))
        for key, row in by_key.items():
            row.series_units = units[key]
            row.series_markup = [_round1(markup_of(tg[key][i], costo[key][i])) for i in range(SERIES_DAYS)]

    def kpis(self) -> Kpis:
        rows = self.rows()
        ok_bound = self._day(self.today - timedelta(days=AGEING_OK_DAYS))
        alert_bound = self._day(self.today - timedelta(days=AGEING_ALERT_DAYS))
        totals = (
            self.db.execute(
                select(
                    func.coalesce(func.sum(rows.c.units), 0).label("units"),
                    func.coalesce(func.sum(rows.c.gross), 0).label("gross"),
                    func.coalesce(func.sum(rows.c.tg), 0).label("tg"),
                    func.coalesce(func.sum(rows.c.mtg), 0).label("mtg"),
                    func.coalesce(func.sum(rows.c.costo), 0).label("costo"),
                    func.coalesce(func.sum(rows.c.prev_units), 0).label("prev_units"),
                    func.coalesce(func.sum(rows.c.prev_gross), 0).label("prev_gross"),
                    func.coalesce(func.sum(rows.c.prev_tg), 0).label("prev_tg"),
                    func.coalesce(func.sum(rows.c.prev_mtg), 0).label("prev_mtg"),
                    func.coalesce(func.sum(rows.c.prev_costo), 0).label("prev_costo"),
                    func.count().label("rows"),
                    func.coalesce(func.sum(case((rows.c.units > 0, 1), else_=0)), 0).label("with_sales"),
                    func.avg(self._days_since(rows.c.ref_day)).label("ageing_avg"),
                    func.coalesce(func.sum(case((rows.c.ref_day >= ok_bound, 1), else_=0)), 0).label("up_to_30"),
                    func.coalesce(
                        func.sum(case((and_(rows.c.ref_day < ok_bound, rows.c.ref_day >= alert_bound), 1), else_=0)),
                        0,
                    ).label("from_31_to_60"),
                    func.coalesce(func.sum(rows.c.a_ageing_60d), 0).label("over_60"),
                )
            )
            .mappings()
            .one()
        )

        # Daily series of the period: the rows' pairs, one statement.
        joined, fp = self._members("")
        days = (self.f.date_to - self.f.date_from).days + 1
        L = self.lines
        series = (
            select(
                L.c.day,
                func.sum(L.c.units).label("units"),
                func.sum(L.c.gross).label("gross"),
                func.sum(L.c.tg).label("tg"),
                func.sum(L.c.mtg).label("mtg"),
                func.sum(L.c.mcosto).label("costo"),
            )
            .select_from(joined)
            .join(L, and_(L.c.product == fp.c.product, L.c.mla == fp.c.mla))
            .where(L.c.day.between(self._day(self.f.date_from), self._day(self.f.date_to)))
            .group_by(L.c.day)
        )
        s_units, s_gross = [0] * days, [Decimal("0")] * days
        s_tg, s_costo = [Decimal("0")] * days, [Decimal("0")] * days
        s_mtg = [Decimal("0")] * days
        for s in self.db.execute(series).mappings():
            i = (_as_date(s["day"]) - self.f.date_from).days
            s_units[i] = int(s["units"] or 0)
            s_gross[i] = Decimal(str(s["gross"] or 0))
            s_tg[i] = Decimal(str(s["tg"] or 0))
            s_mtg[i] = Decimal(str(s["mtg"] or 0))
            s_costo[i] = Decimal(str(s["costo"] or 0))
        dec = lambda v: Decimal(str(v or 0))  # noqa: E731
        return Kpis(
            units=int(totals["units"]),
            gross=dec(totals["gross"]),
            tg=dec(totals["tg"]),
            mtg=dec(totals["mtg"]),
            costo=dec(totals["costo"]),
            prev_units=int(totals["prev_units"]),
            prev_gross=dec(totals["prev_gross"]),
            prev_tg=dec(totals["prev_tg"]),
            prev_mtg=dec(totals["prev_mtg"]),
            prev_costo=dec(totals["prev_costo"]),
            rows=int(totals["rows"]),
            with_sales=int(totals["with_sales"]),
            ageing_avg=float(totals["ageing_avg"]) if totals["ageing_avg"] is not None else None,
            up_to_30=int(totals["up_to_30"]),
            from_31_to_60=int(totals["from_31_to_60"]),
            over_60=int(totals["over_60"]),
            series_units=s_units,
            series_gross=[float(v) for v in s_gross],
            series_tg=[float(v) for v in s_tg],
            series_markup=[_round1(markup_of(s_mtg[i], s_costo[i])) for i in range(days)],
        )

    def _members(self, skip: str):
        """The pairs (with their attributes) of the rows that survive every
        filter but `skip`, as `(join, pairs)`. Both sides are MATERIALIZED
        CTEs: inlined, the planner under-estimates a filtered pair set and
        nests loops over it (measured: 0.7 s for one chip count)."""
        fp = self.filtered_pairs(skip)
        rows = self.rows(skip=skip)
        pairs = select(fp).cte(f"members_{skip or 'all'}").prefix_with("MATERIALIZED", dialect="postgresql")
        keys = select(rows.c.rk).cte(f"keys_{skip or 'all'}").prefix_with("MATERIALIZED", dialect="postgresql")
        return pairs.join(keys, keys.c.rk == pairs.c.rk), pairs

    def facets(self) -> Facets:
        """Every chip count, each with its OWN axis cleared: five fixed
        statements (stores, "Todas", status, type, alerts)."""
        joined, fp = self._members("stores")
        bucket = func.coalesce(cast(fp.c.store_id, String), literal(NO_STORE))
        stores = {
            str(b): int(n)
            for b, n in self.db.execute(
                select(bucket, func.count(func.distinct(fp.c.rk))).select_from(joined).group_by(bucket)
            )
        }
        rows = self.rows(skip="stores")
        stores_total = int(self.db.execute(select(func.count()).select_from(rows)).scalar() or 0)

        joined, fp = self._members("pub_status")
        pub_status = {
            str(st): int(n)
            for st, n in self.db.execute(
                select(fp.c.status, func.count(func.distinct(fp.c.rk)))
                .select_from(joined)
                .where(fp.c.status.isnot(None))
                .group_by(fp.c.status)
            )
        }

        joined, fp = self._members("pub_type")
        type_conds = {
            "clasica": fp.c.listing_type == "clasica",
            "premium": fp.c.listing_type == "premium",
            "catalogo": fp.c.is_catalog == True,  # noqa: E712 -- untyped temp-table column
            "full": fp.c.is_full == True,  # noqa: E712
        }
        type_row = (
            self.db.execute(
                select(
                    *(
                        func.count(func.distinct(case((cond, fp.c.rk), else_=None))).label(name)
                        for name, cond in type_conds.items()
                    )
                ).select_from(joined)
            )
            .mappings()
            .one()
        )
        pub_type = {name: int(type_row[name] or 0) for name in type_conds if type_row[name]}

        rows = self.rows(skip="alerts")
        alert_row = (
            self.db.execute(select(*(func.coalesce(func.sum(rows.c[f"a_{name}"]), 0).label(name) for name in ALERTS)))
            .mappings()
            .one()
        )
        alerts = {name: int(alert_row[name]) for name in ALERTS}
        return Facets(stores=stores, stores_total=stores_total, pub_status=pub_status, pub_type=pub_type, alerts=alerts)


def refreshed_at(db: Session) -> Optional[datetime]:
    """When the sales were last brought up to date from Mercado Libre: the
    latest COMPLETE pass of the sweep or the activity drain -- the same
    source as Ventas ML's sync-status. `None` before any."""
    last = (
        db.query(func.max(MlOpsSyncCursor.last_success_at)).filter(MlOpsSyncCursor.name.in_(FRESHNESS_CURSORS)).scalar()
    )
    return _as_aware(_as_datetime(last))


__all__ = [
    "ALERTS",
    "AGEING_ALERT_DAYS",
    "Board",
    "BoardFilter",
    "COMPARE",
    "GROUP_BY",
    "Kpis",
    "MARGIN_SORTS",
    "PUB_STATUSES",
    "PUB_TYPES",
    "Pub",
    "Row",
    "SORTS",
    "markup_of",
    "now_utc",
    "previous_period",
    "refreshed_at",
    "today_business",
]
