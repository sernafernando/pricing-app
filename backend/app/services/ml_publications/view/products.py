"""The Producto view of the Publicaciones screen (`GET /ml-publications/view/products`): one row per LINKED product over
the MLAs the screen's filter selects, its figures the sum of its publications' Métricas ML figures over the last 30
business days.

One source of truth on this screen: the publication -> product link (`ml_item_product_links`, item level, joined
exactly as the base select joins it). A row groups the publications linked to one product; "Sin producto" groups the
ones with no linked product -- the very sets `/items?producto=` and `/items?sin_producto=` list under the same
filters, so a row's `publications_count` is what opening it shows. The product a sale's frozen cost or the ERP
mirror names (what Métricas ML's own product rows group by) plays no part here.

Nothing is computed twice (one metric, one source). The filter becomes the Board's MLA set (`BoardFilter.mla_source`)
and the Board answers its PUBLICATION rows -- the figures `/items` shows for each MLA (`row_metrics`). ONE statement
then sums them per linked product, sorts and pages:

* units, windows, gross and Total Gauss are summed; the markup is the ratio of the summed markup numerator over the
  summed cost (`board.markup_of`, the Board's own aggregate rule), never an average of percentages; the order-group
  all-or-nothing of numerator and cost is already in each publication's components, and a sum keeps it;
* the last sale is the latest, the ageing counts from it (else from the earliest publication start), as the Board
  ages its own product rows; the 90-day series sums the publications' daily lines (`Board.read_series`);
* a linked publication the Board has no row for (never sold, unknown to the ERP mirror) still counts in its product,
  with no figures; a product none of whose publications has a Board row has no figures at all (`without_figures`);
* the figure sorts put the products without a sale in the 30 days last either way, as `/items` does; the product id
  closes every tie, so pages never repeat or skip a row.

ONE Board per request and a fixed number of statements whatever the page. `scope_pairs=None`: no PM scoping. Nothing
commits and nothing is written. Postgres only (the Board's temp tables); its tests are `@pytest.mark.postgres`.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Iterator, Optional, Sequence

from sqlalchemy import ARRAY, Date, Integer, String, Text, and_, any_, case, cast, func, literal, null, select
from sqlalchemy.orm import Session

from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.sales import NO_PRODUCT
from app.services.ml_publications.view import row_metrics
from app.services.ml_publications.view.caps import MAX_EXPLICIT_PRODUCT_IDS
from app.services.ml_publications.view.filters import (
    LINK_ITEM_LEVEL,
    FilterError,
    PublicationFilter,
    T,
    build_base_select,
    erp_stock,
    product_select,
    publication_filter_in,
)
from app.services.ml_publications.view.listing import markup_accepted, resolve_pm_pairs
from app.services.ml_publications.view.markup_service import MarkupQuery

# `orden` -> (the summed row's column, whether it is a margin figure: `ml_metricas.ver_ganancia` only, whether it is a
# Métricas figure: `ml_metricas.ver` only). The figure names are the ones `/items` sorts by.
PRODUCT_SORTS: dict[str, tuple[str, bool, bool]] = {
    "facturado_30d": ("gross", False, True),
    "unidades_7d": ("w7d", False, True),
    "unidades_30d": ("w30d", False, True),
    "markup_30d": ("markup", True, True),
    "total_gauss_30d": ("tg", True, True),
    "titulo": ("name", False, False),
}
SortKeys = Sequence[tuple[str, bool]]  # the sort keys after the first, each with whether it is descending
DEFAULT_SORT = "facturado_30d"
NEUTRAL_SORT = "titulo"  # the default for a caller who may not see Métricas' figures
NO_PRODUCT_LABEL = "Sin producto"

# The Board's publication-row figures a product sums.
SUMMED = ("units", "gross", "tg", "mtg", "costo", "prev_units", "prev_gross", "prev_tg", "prev_mtg", "prev_costo")
WINDOW_COLUMNS = {"3d": "w3d", "7d": "w7d", "15d": "w15d", "30d": "w30d"}


def needs_margin(key: str) -> bool:
    return PRODUCT_SORTS[key][1]


def needs_metrics(key: str) -> bool:
    return PRODUCT_SORTS[key][2]


def parse_sort(orden: str, then: SortKeys = ()) -> str:
    """The first sort key, every key checked (`then`: the keys after it, Productos' multi-column sort)."""
    key = orden.strip()
    for name in (key, *(name for name, _ in then)):
        if name not in PRODUCT_SORTS:
            raise FilterError("orden", f"must be one of {', '.join(PRODUCT_SORTS)}")
    return key


@dataclass(frozen=True)
class ProductsPage:
    rows: list[board.Row]  # `product_item_id` is `NO_PRODUCT` on the "Sin producto" row
    total: int  # the product rows of the whole filtered set
    mla_count: int  # the publications the filter selects
    without_figures: frozenset[str] = field(default_factory=frozenset)  # keys of rows with no Board row at all


def _members(mla_set: Any) -> Any:
    """Each MLA of the set with its linked product -- the LINK's product id, even when the product is gone from the
    catalog (its name then reads "Producto #<id>") -- through the base select's own item-level link join
    (`filters.joined`), so the grouping is exactly what `/items?producto=` and `sin_producto` filter on."""
    return (
        select(
            mla_set.c.mla,
            # NO_PRODUCT (0) is the Board's own "no product" sentinel; ERP item ids are positive.
            func.coalesce(T.l.producto_item_id, NO_PRODUCT).label("product"),
            T.p.descripcion,
            T.p.codigo,
            T.p.marca,
            erp_stock().label("stock"),  # `/items`' own rule: only a `linked` link gives the ERP stock
        )
        .select_from(mla_set)
        .outerjoin(T.l, and_(T.l.item_id == mla_set.c.mla, T.l.variation_id == LINK_ITEM_LEVEL))
        .outerjoin(T.p, T.p.item_id == T.l.producto_item_id)
        .subquery("members")
    )


def _summed(members: Any, rows: Any) -> Any:
    """One row per linked product: its publications' Board figures summed, its count, its markup."""
    g = (
        select(
            members.c.product,
            func.max(members.c.descripcion).label("descripcion"),
            func.max(members.c.codigo).label("codigo"),
            func.max(members.c.marca).label("marca"),
            func.max(members.c.stock).label("stock"),
            func.count(members.c.mla).label("pubs"),
            func.count(rows.c.rk).label("board_rows"),
            *(func.sum(rows.c[name]).label(name) for name in (*SUMMED, *WINDOW_COLUMNS.values(), "u24")),
            func.max(rows.c.last_day).label("last_day"),
            func.max(rows.c.last_at).label("last_at"),
            func.min(rows.c.start_day).label("start_day"),
        )
        .select_from(members.outerjoin(rows, rows.c.rk == members.c.mla))
        .group_by(members.c.product)
        .subquery("products")
    )
    markup = case((g.c.costo > 0, g.c.mtg * 100 / g.c.costo), else_=None)
    # What the row shows (and its name sort): the description, else the code, else the link's id -- a product gone
    # from the catalog keeps a name of its own; "Sin producto" for the publications with no linked product.
    name = case(
        (g.c.product == NO_PRODUCT, literal(NO_PRODUCT_LABEL)),
        else_=func.coalesce(
            func.nullif(g.c.descripcion, ""),
            func.nullif(g.c.codigo, ""),
            literal("Producto #") + cast(g.c.product, String),
        ),
    )
    return select(*g.c, markup.label("markup"), name.label("name")).subquery("product_rows")


def _sin_mla_rows(db: Session, f: PublicationFilter) -> Any:
    """The "Sin MLA" products (`filters.product_select`) shaped as `_summed`'s rows: no publication, so no Board and
    no figure -- what the row shows is the product's own name, code, brand and ERP stock."""
    f = resolve_pm_pairs(db, f)
    name = func.coalesce(
        func.nullif(T.p.descripcion, ""), func.nullif(T.p.codigo, ""), literal("Producto #") + cast(T.p.item_id, String)
    )
    nothing = (*SUMMED, *WINDOW_COLUMNS.values(), "u24", "last_day", "last_at", "start_day", "markup")
    return product_select(
        f,
        T.p.item_id.label("product"),
        T.p.descripcion,
        T.p.codigo,
        T.p.marca,
        T.p.stock,
        literal(0).label("pubs"),
        literal(0).label("board_rows"),
        *(null().label(column) for column in nothing),
        name.label("name"),
    ).subquery("product_rows")


def applied_sort(f: PublicationFilter, key: str, descending: bool, then: SortKeys = ()) -> tuple[str, bool, SortKeys]:
    """The sort the rows of `f` really come in: a "Sin MLA" product has no publication, so no Métricas figure, and
    the sort is the name alone, in the direction asked for it, A to Z when it was not asked (the response says so,
    never the sort that was asked)."""
    if not f.sin_mla:
        return key, descending, tuple(then)
    by_name = dict(((key, descending), *then)).get(NEUTRAL_SORT, False)
    return NEUTRAL_SORT, by_name, ()


def sin_mla_count(db: Session, f: PublicationFilter) -> Optional[int]:
    """How many "Sin MLA" products the product filters of `f` select (the card of Productos); None when `f` asks
    something of the publications, which a product without any cannot answer."""
    if publication_filter_in(f) is not None:
        return None
    rows = _sin_mla_rows(db, replace(f, sin_mla=True))
    return int(db.execute(select(func.count()).select_from(rows)).scalar_one())


def _by(rows: Any, key: str, descending: bool) -> tuple[Any, ...]:
    column = rows.c[PRODUCT_SORTS[key][0]]
    if key == NEUTRAL_SORT:
        # By the name the row shows, case-insensitively; "Sin producto" is not a name: last either way (among the
        # ties of the keys before it when the name is not the first key).
        name = func.lower(column)
        return (rows.c.product == NO_PRODUCT).asc(), name.desc() if descending else name.asc()
    figure = case((rows.c.units > 0, column), else_=None)  # no sale in the 30 days: no figure, last
    return ((figure.desc() if descending else figure.asc()).nulls_last(),)


def _ordered(rows: Any, key: str, descending: bool, then: SortKeys = ()) -> tuple[Any, ...]:
    keys = ((key, descending), *then)
    return (*(clause for name, desc in keys for clause in _by(rows, name, desc)), rows.c.product.asc())


def _row(r: Any, today: date) -> board.Row:
    product = int(r["product"])
    # `board.as_date`, `as_datetime` and `as_aware` read the Board's temp-table values (SQLite text vs Postgres
    # types), so a product row reads them exactly as the Board's own rows do.
    ref_day = board.as_date(r["last_day"]) or board.as_date(r["start_day"])
    return board.Row(
        key=str(product),
        product_item_id=product,
        mla=None,
        title=r["name"],
        sku=r["codigo"],
        marca=r["marca"],
        publications_count=int(r["pubs"]),
        units=int(r["units"] or 0),
        gross=board.cents(r["gross"]),
        tg=board.cents(r["tg"]),
        mtg=board.cents(r["mtg"]),
        costo=board.cents(r["costo"]),
        prev_tg=board.cents(r["prev_tg"]),
        prev_mtg=board.cents(r["prev_mtg"]),
        prev_costo=board.cents(r["prev_costo"]),
        windows={name: int(r[column] or 0) for name, column in WINDOW_COLUMNS.items()},
        units_24h=int(r["u24"] or 0),
        last_sale_at=board.as_aware(board.as_datetime(r["last_at"])),
        ageing_days=(today - ref_day).days if ref_day else None,
        stock=int(r["stock"]) if r["stock"] is not None else None,
    )


def _series(b: board.Board, members: Any, by_key: dict[str, board.Row]) -> None:
    """The page's 90-day series: the publications' daily lines summed per linked product, read by the Board's own
    reader (`read_series`: units summed, each day's markup from that day's summed components)."""
    if not by_key:
        return
    fp, lines = b.filtered_pairs(), b.lines
    key = cast(members.c.product, String)
    series = (
        select(
            key.label("rk"),
            lines.c.day,
            func.sum(lines.c.units).label("units"),
            func.sum(lines.c.mtg).label("tg"),
            func.sum(lines.c.mcosto).label("costo"),
        )
        .select_from(fp)
        .join(lines, and_(lines.c.product == fp.c.product, lines.c.mla == fp.c.mla))
        .join(members, members.c.mla == fp.c.mla)
        .where(
            members.c.product.in_([int(k) for k in by_key]),
            lines.c.day.between(literal(b.series_from, Date), literal(b.f.date_to, Date)),
        )
        .group_by(members.c.product, lines.c.day)
    )
    # The Board's own series reader (each day's markup from that day's summed components), so a product's
    # sparklines equal the sum of its publications'.
    b.read_series(by_key, series)


@contextmanager
def _product_rows(db: Session, f: PublicationFilter, only: Optional[Sequence[int]] = None) -> Iterator[tuple]:
    """The Board over the MLAs `f` selects and the summed product rows over it: `(board, members, rows)`. `only`
    narrows the MLA set to the publications linked to those products (`NO_PRODUCT`: no link) -- every one of them
    `f` selects, so each product's count and figures are the very ones of the whole set."""
    # mejor oferta is a product's (any of its publications), as in Productos
    f = replace(resolve_pm_pairs(db, f), oferta_per_product=True)
    first, last = row_metrics.window(board.today_business())
    mla_source = build_base_select(f, T.i.item_id)
    if only is not None:
        product = func.coalesce(T.l.producto_item_id, NO_PRODUCT)
        mla_source = mla_source.where(product == any_(literal(list(only), ARRAY(Integer))))
    board_filter = board.BoardFilter(date_from=first, date_to=last, group_by="publication", mla_source=mla_source)
    with board.Board(db, board_filter, scope_pairs=None) as b:
        members = _members(b.mla_set)
        yield b, members, _summed(members, b.rows())


def list_products(
    db: Session, f: PublicationFilter, orden: str, descending: bool, limit: int, offset: int, then: SortKeys = ()
) -> ProductsPage:
    """The linked-product rows of the MLAs `f` selects at `[offset, offset + limit)`, in the order `orden` (then
    `then`) names."""
    key = parse_sort(orden, then)
    if f.sin_mla:
        rows = _sin_mla_rows(db, f)
        total = db.execute(select(func.count()).select_from(rows)).scalar_one()
        found = []
        if offset < total:
            ordered = _ordered(rows, *applied_sort(f, key, descending, then))
            page = select(rows).order_by(*ordered).limit(limit).offset(offset)
            found = list(db.execute(page).mappings())
        today = board.today_business()
        return ProductsPage([_row(r, today) for r in found], int(total), 0, frozenset(str(r["product"]) for r in found))
    with _product_rows(db, f) as (b, members, rows):
        total, mla_count = db.execute(
            select(func.count(), func.coalesce(func.sum(rows.c.pubs), 0)).select_from(rows)
        ).one()
        found: list[Any] = []
        if offset < total:
            page = select(rows).order_by(*_ordered(rows, key, descending, then)).limit(limit).offset(offset)
            found = list(db.execute(page).mappings())
        out = [_row(r, b.today) for r in found]
        _series(b, members, {row.key: row for row in out})
    without = frozenset(str(r["product"]) for r in found if not r["board_rows"])
    return ProductsPage(out, int(total), int(mla_count), without)


def ordered_product_keys(
    db: Session, f: PublicationFilter, orden: str, descending: bool, cap: Optional[int], then: SortKeys = ()
) -> list[int]:
    """The product ids (`NO_PRODUCT` for "Sin producto") of every row of the Producto view, at most `cap` (every
    one when None), in the very order `list_products` pages them: the keys an export fixes before reading its pages."""
    key = parse_sort(orden, then)
    if f.sin_mla:
        rows = _sin_mla_rows(db, f)
        query = select(rows.c.product).order_by(*_ordered(rows, *applied_sort(f, key, descending, then))).limit(cap)
        return [int(product) for product in db.execute(query).scalars()]
    with _product_rows(db, f) as (_, _, rows):
        query = select(rows.c.product).order_by(*_ordered(rows, key, descending, then)).limit(cap)
        return [int(product) for product in db.execute(query).scalars()]


def products_for_keys(db: Session, f: PublicationFilter, keys: Sequence[int]) -> ProductsPage:
    """The product rows of `keys` in their order, built as `list_products` builds them (no series: the export does
    not draw them). A product with no publication left under `f` is skipped."""
    if not keys:
        return ProductsPage([], 0, 0)
    if f.sin_mla:
        rows = _sin_mla_rows(db, f)
        query = select(rows).where(rows.c.product == any_(literal(list(keys), ARRAY(Integer))))
        by_key = {int(r["product"]): r for r in db.execute(query).mappings()}
        found = [by_key[k] for k in keys if k in by_key]
        today = board.today_business()
        return ProductsPage([_row(r, today) for r in found], len(found), 0, frozenset(str(k) for k in by_key))
    with _product_rows(db, f, only=keys) as (b, _, rows):
        by_product = {int(r["product"]): r for r in db.execute(select(rows)).mappings()}
    found = [by_product[k] for k in keys if k in by_product]
    without = frozenset(str(r["product"]) for r in found if not r["board_rows"])
    return ProductsPage([_row(r, b.today) for r in found], len(found), sum(int(r["pubs"]) for r in found), without)


# The most products one bulk action may name, shared with the bulk endpoints (`caps`). Over it the request is refused,
# never truncated (a bulk write over part of the set is the bug).
MAX_PRODUCT_IDS = MAX_EXPLICIT_PRODUCT_IDS


class TooManyProducts(Exception):
    def __init__(self, count: int, cap: int) -> None:
        super().__init__(f"{count} products over the cap of {cap}")
        self.count = count
        self.cap = cap


@dataclass(frozen=True)
class ProductIds:
    item_ids: list[int]  # the distinct linked products in the ERP catalog, ascending
    sin_producto: int  # the matching publications with no linked product (left out of `item_ids`)
    fuera_de_catalogo: int  # the linked products no longer in the ERP catalog (left out: no bulk write can price them)


def product_ids(db: Session, f: PublicationFilter, markup: Optional[MarkupQuery] = None) -> ProductIds:
    """The linked products of the MLAs `f` selects -- the very grouping `list_products` makes (the base select's
    item-level link), so their count is its product rows. Unlike `list_products`, mejor oferta is asked the way the
    caller asks it (`oferta_por_producto`): in the publication view a product is in the set when one of ITS matching
    publications is, which is what the operator sees.

    `markup` (its filter active) narrows the MLAs as `/items` does, with the same post-query step
    (`listing.markup_accepted`) over the whole filtered set. A linked product the ERP catalog no longer has is left
    out and counted (`fuera_de_catalogo`): the bulk endpoints cannot price it. Raises `TooManyProducts` over
    `MAX_PRODUCT_IDS`. With `sin_mla`, the "Sin MLA" products: no publication, so nothing left out to count."""
    if f.sin_mla:
        if markup is not None and markup.filter.active:
            active = markup.filter
            param = "markup_neg" if active.negative else "markup_min" if active.minimum is not None else "markup_max"
            raise FilterError(param, "the markup filters do not apply to the products without MLA (con_mla=false)")
        rows = _sin_mla_rows(db, f)
        found = db.execute(
            select(rows.c.product, func.count().over().label("total"))
            .order_by(rows.c.product)
            .limit(MAX_PRODUCT_IDS + 1)
        ).all()
        count = found[0].total if found else 0
        if count > MAX_PRODUCT_IDS:
            raise TooManyProducts(int(count), MAX_PRODUCT_IDS)
        return ProductIds([int(row.product) for row in found], 0, 0)
    f = resolve_pm_pairs(db, f)
    base = build_base_select(
        f, T.i.item_id.label("mla"), T.l.producto_item_id.label("product"), T.p.item_id.label("in_catalog")
    )
    if markup is not None and markup.filter.active:
        _, kept = markup_accepted(db, f, markup)
        base = base.where(T.i.item_id == any_(literal(sorted(kept), ARRAY(Text))))
    members = base.subquery("m")
    linked = members.c.product.isnot(None) & (members.c.product != NO_PRODUCT)
    priceable = linked & members.c.in_catalog.isnot(None)
    # The ids and their total come from ONE statement (a window over the distinct ids, evaluated before the LIMIT):
    # the cap checks the very snapshot the list is read from, so a product linked meanwhile never slips a list past
    # it. LIMIT cap+1 keeps an over-cap answer small while the window still reports the true total.
    distinct_ids = select(members.c.product).where(priceable).distinct().subquery("ids")
    found = db.execute(
        select(distinct_ids.c.product, func.count().over().label("total"))
        .order_by(distinct_ids.c.product)
        .limit(MAX_PRODUCT_IDS + 1)
    ).all()
    count = found[0].total if found else 0
    if count > MAX_PRODUCT_IDS:
        raise TooManyProducts(int(count), MAX_PRODUCT_IDS)
    sin_producto, gone = db.execute(
        select(
            func.count(func.distinct(case((linked, None), else_=members.c.mla))),
            func.count(func.distinct(case((linked & members.c.in_catalog.is_(None), members.c.product), else_=None))),
        ).select_from(members)
    ).one()
    return ProductIds([int(row.product) for row in found], int(sin_producto), int(gone))
