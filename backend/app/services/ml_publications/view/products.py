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
  ages its own product rows; the 90-day series sums the publications' daily lines (`Board._read_series`);
* a linked publication the Board has no row for (never sold, unknown to the ERP mirror) still counts in its product,
  with no figures; a product none of whose publications has a Board row has no figures at all (`without_figures`);
* the figure sorts put the products without a sale in the 30 days last either way, as `/items` does; the product id
  closes every tie, so pages never repeat or skip a row.

ONE Board per request and a fixed number of statements whatever the page. `scope_pairs=None`: no PM scoping. Nothing
commits and nothing is written. Postgres only (the Board's temp tables); its tests are `@pytest.mark.postgres`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Date, String, and_, case, cast, func, literal, select
from sqlalchemy.orm import Session

from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.sales import NO_PRODUCT
from app.services.ml_publications.view import row_metrics
from app.services.ml_publications.view.filters import (
    LINK_ITEM_LEVEL,
    FilterError,
    PublicationFilter,
    T,
    build_base_select,
    erp_stock,
)
from app.services.ml_publications.view.listing import resolve_pm_pairs

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


def parse_sort(orden: str) -> str:
    key = orden.strip()
    if key not in PRODUCT_SORTS:
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


def _ordered(rows: Any, key: str, descending: bool) -> tuple[Any, ...]:
    column = rows.c[PRODUCT_SORTS[key][0]]
    if key == NEUTRAL_SORT:
        # By the name the row shows, case-insensitively; "Sin producto" is not a name: pinned last either way.
        name = func.lower(column)
        return (
            (rows.c.product == NO_PRODUCT).asc(),
            name.desc() if descending else name.asc(),
            rows.c.product.asc(),
        )
    figure = case((rows.c.units > 0, column), else_=None)  # no sale in the 30 days: no figure, last
    return ((figure.desc() if descending else figure.asc()).nulls_last(), rows.c.product.asc())


def _row(r: Any, today: date) -> board.Row:
    product = int(r["product"])
    # ponytail: `board._as_date`, `_as_datetime` and `_as_aware` are the Board's private readers of its temp-table
    # values (SQLite text vs Postgres types); reused so a product row reads them exactly as the Board's own rows do.
    # Switch to their public names once PR #1595 (which owns `ml_daily_metrics/board.py` now) merges.
    ref_day = board._as_date(r["last_day"]) or board._as_date(r["start_day"])
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
        last_sale_at=board._as_aware(board._as_datetime(r["last_at"])),  # ponytail: see `_as_date` above
        ageing_days=(today - ref_day).days if ref_day else None,
        stock=int(r["stock"]) if r["stock"] is not None else None,
    )


def _series(b: board.Board, members: Any, by_key: dict[str, board.Row]) -> None:
    """The page's 90-day series: the publications' daily lines summed per linked product, read by the Board's own
    reader (`_read_series`: units summed, each day's markup from that day's summed components)."""
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
    # ponytail: `Board._read_series` is private; it is the Board's own series reader (each day's markup from that
    # day's summed components), reused so a product's sparklines equal the sum of its publications'. Switch to its
    # public name once PR #1595 (which owns `ml_daily_metrics/board.py` now) merges.
    b._read_series(by_key, series)


def list_products(
    db: Session, f: PublicationFilter, orden: str, descending: bool, limit: int, offset: int
) -> ProductsPage:
    """The linked-product rows of the MLAs `f` selects at `[offset, offset + limit)`, in the order `orden` names."""
    key = parse_sort(orden)
    f = resolve_pm_pairs(db, f)
    first, last = row_metrics.window(board.today_business())
    board_filter = board.BoardFilter(
        date_from=first, date_to=last, group_by="publication", mla_source=build_base_select(f, T.i.item_id)
    )
    with board.Board(db, board_filter, scope_pairs=None) as b:
        members = _members(b.mla_set)
        rows = _summed(members, b.rows())
        total, mla_count = db.execute(
            select(func.count(), func.coalesce(func.sum(rows.c.pubs), 0)).select_from(rows)
        ).one()
        found: list[Any] = []
        if offset < total:
            page = select(rows).order_by(*_ordered(rows, key, descending)).limit(limit).offset(offset)
            found = list(db.execute(page).mappings())
        out = [_row(r, b.today) for r in found]
        _series(b, members, {row.key: row for row in out})
    without = frozenset(str(r["product"]) for r in found if not r["board_rows"])
    return ProductsPage(out, int(total), int(mla_count), without)
