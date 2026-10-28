"""The Producto view of Publicaciones: one row per LINKED product over the MLAs the screen's filter selects, its
figures the sum of its publications' Métricas ML figures over the last 30 business days.

Real Postgres: the store tables and the Board's tables share one throwaway schema, as they share the database in
production. What matters, all of it the screen's one source of truth (the publication -> product link):

* the rows group by the link, never by the product a sale's cost or the ERP mirror names; "Sin producto" is no link;
* a product's `publications_count` is exactly what `/items?producto=` (or `sin_producto`) lists under the same filters;
* a product's figures are the sum of its publications' own figures (the per-publication Board, as the list shows
  them), the markup the ratio of the summed components -- never an average of percentages;
* a linked publication the Board knows nothing about is still counted, with no figures; nothing disappears;
* the order is total and stable across pages, an empty selection is empty, and the page costs ONE Board.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.sales import NO_PRODUCT
from app.services.ml_publications.view import products, row_metrics
from app.services.ml_publications.view.filters import T, build_base_select, parse_filter
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_units_sold_postgres import order

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
SOLD = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)  # 12:00 in Buenos Aires
EARLIER = datetime(2026, 9, 27, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", False)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _sell(
    session: Session, order_id: int, mla: str, qty: int, cost_product: int | None, *, tg="1", costo="1", when=SOLD
):
    """One order of `qty` units of `mla`. Its frozen cost names `cost_product` (None: no cost row) -- what the Board
    groups by, on purpose different from the link below for some MLAs."""
    order(session, order_id, [(mla, None, qty)], accredited=when)
    costs = MlOrderItemCosto.order_id == order_id
    if cost_product is None:
        session.execute(delete(MlOrderItemCosto).where(costs))
    else:
        session.execute(update(MlOrderItemCosto).where(costs).values(producto_item_id=cost_product))
    session.execute(
        update(MlOrderMetrics)
        .where(MlOrderMetrics.order_id == order_id)
        .values(total_gauss=Decimal(tg), costo_mercaderia=Decimal(costo))
    )


@pytest.fixture()
def store(mlpub_pg):  # noqa: F811
    from app.models.producto import ProductoERP

    ProductoERP.__table__.create(bind=mlpub_pg)
    seed.create_board_tables(mlpub_pg)
    with mlpub_pg.begin() as conn:
        seed.add_product(conn, 70, "A70", "Router AX", marca="TP-Link", stock=9)
        seed.add_product(conn, 71, "B71", "Switch 8p", marca="Mercusys")
        seed.add_product(conn, 72, "C72", "Antena", marca="Ubiquiti")
        for mla, status in (("MLA1", "active"), ("MLA2", "active"), ("MLA3", "paused"), ("MLA4", "active")):
            seed.add_item(conn, mla, status=status)
        seed.add_item(conn, "MLA5", status="active")  # linked to 70, never sold, unknown to the ERP mirror
        seed.add_item(conn, "MLA6", status="active")  # linked to 72, never sold: a product with no figures at all
        seed.add_item(conn, "MLA7", status="active")  # linked to 71, sold with no cost row
        seed.add_link(conn, "MLA1", 70)  # its sale's cost names 71: the link wins
        seed.add_link(conn, "MLA2", 71)
        seed.add_link(conn, "MLA3", 70)
        seed.add_link(conn, "MLA5", 70)
        seed.add_link(conn, "MLA6", 72)
        seed.add_link(conn, "MLA7", 71)
    session = sessionmaker(bind=mlpub_pg)()
    _sell(session, 1, "MLA1", 2, 71, tg="30", costo="100")
    _sell(session, 2, "MLA1", 1, 71, tg="10", costo="300", when=EARLIER)
    _sell(session, 3, "MLA2", 5, 71, tg="5", costo="10")
    _sell(session, 4, "MLA3", 100, 70)  # paused: filtered out below
    _sell(session, 5, "MLA4", 1, None)  # no link (and no cost): "Sin producto"
    _sell(session, 6, "MLA7", 4, None, tg="8", costo="40")
    session.commit()
    session.close()
    reader = sessionmaker(bind=mlpub_pg)()
    yield reader
    reader.rollback()
    reader.close()


def page(
    db: Session, orden: str = products.DEFAULT_SORT, descending: bool = True, limit=50, offset=0, then=(), **filters
):
    got = products.list_products(db, parse_filter(**filters), orden, descending, limit, offset, then=then)
    db.rollback()  # each request ends its transaction, as the router does
    return got


def by_product(got) -> dict[int, board.Row]:
    return {row.product_item_id: row for row in got.rows}


def expansion(db: Session, row: board.Row, **filters) -> list[str]:
    """What the screen lists when the row is opened: `/items` with the row's params over the same filters."""
    extra = {"sin_producto": True} if row.product_item_id == NO_PRODUCT else {"producto": str(row.product_item_id)}
    query = build_base_select(parse_filter(**filters, **extra), T.i.item_id)
    return sorted(mla for (mla,) in db.execute(query))


def test_the_rows_group_by_the_link_not_by_the_cost_or_mirror_product(store) -> None:
    rows = by_product(page(store, estado="active"))
    assert set(rows) == {70, 71, 72, NO_PRODUCT}
    assert rows[70].units == 3  # MLA1's sales, whose cost names product 71
    assert rows[71].units == 9  # MLA2 and MLA7 (no cost row, but linked)
    assert rows[NO_PRODUCT].units == 1 and rows[NO_PRODUCT].title == "Sin producto"
    assert (rows[70].title, rows[70].sku, rows[70].marca, rows[70].stock) == ("Router AX", "A70", "TP-Link", 9)


def test_publications_count_is_what_the_expansion_lists(store) -> None:
    for filters in ({"estado": "active"}, {}):
        for row in page(store, **filters).rows:
            assert row.publications_count == len(expansion(store, row, **filters)), row.key


def test_a_publication_the_board_does_not_know_is_still_counted_without_figures(store) -> None:
    got = page(store, estado="active")
    rows = by_product(got)
    assert rows[70].publications_count == 2  # MLA1 and the never-sold MLA5
    assert rows[72].publications_count == 1 and str(72) in got.without_figures
    assert str(70) not in got.without_figures
    assert got.mla_count == 6 and sum(row.publications_count for row in got.rows) == 6


def test_a_product_is_the_sum_of_its_publications(store) -> None:
    rows = page(store, estado="active").rows
    for row in rows:
        children = row_metrics.metrics_by_mla(store, expansion(store, row, estado="active"))
        store.rollback()
        kids = list(children.values())
        assert row.units == sum(k.units for k in kids)
        assert row.gross == sum((k.gross for k in kids), Decimal("0"))
        assert row.tg == sum((k.tg for k in kids), Decimal("0"))
        assert row.windows["7d"] == sum(k.windows["7d"] for k in kids)
        assert row.windows["30d"] == sum(k.windows["30d"] for k in kids)
        assert row.series_units == [sum(day) for day in zip(*(k.series_units for k in kids))] or not kids
        mtg, costo = sum((k.mtg for k in kids), Decimal("0")), sum((k.costo for k in kids), Decimal("0"))
        assert (row.mtg, row.costo) == (mtg, costo)
        assert row.markup == board.markup_of(mtg, costo)


def test_the_markup_is_the_ratio_of_the_summed_components_not_an_average(store) -> None:
    row = by_product(page(store, estado="active"))[71]
    kids = list(row_metrics.metrics_by_mla(store, expansion(store, row, estado="active")).values())
    markups = [k.markup for k in kids]
    assert len(markups) == 2 and None not in markups and markups[0] != markups[1]
    summed = board.markup_of(sum((k.mtg for k in kids), Decimal("0")), sum((k.costo for k in kids), Decimal("0")))
    assert row.markup == summed != sum(markups) / 2


def test_sorted_by_a_figure_with_no_sales_last_and_paged_without_repeats(store) -> None:
    desc = [row.product_item_id for row in page(store, "unidades_30d", True, estado="active").rows]
    assert desc == [71, 70, NO_PRODUCT, 72]
    asc = [row.product_item_id for row in page(store, "unidades_30d", False, estado="active").rows]
    assert asc == [NO_PRODUCT, 70, 71, 72]  # no sales goes last either way
    first = page(store, "unidades_30d", True, limit=2, estado="active")
    second = page(store, "unidades_30d", True, limit=2, offset=2, estado="active")
    assert [r.product_item_id for r in first.rows + second.rows] == desc
    assert first.total == second.total == 4


def test_sorted_by_markup(store) -> None:
    got = page(store, "markup_30d", True, estado="active").rows
    with_markup = [row for row in got if row.units > 0 and row.markup is not None]
    assert [row.markup for row in with_markup] == sorted((row.markup for row in with_markup), reverse=True)
    assert got[: len(with_markup)] == with_markup  # no markup (or no sales): last


def test_sorted_by_name_with_sin_producto_last(store) -> None:
    asc = [row.product_item_id for row in page(store, "titulo", False, estado="active").rows]
    assert asc == [72, 70, 71, NO_PRODUCT]


def test_a_next_key_breaks_the_ties_of_the_first_and_the_export_keeps_the_order(store) -> None:
    with store.get_bind().begin() as conn:  # a second product with no figures: it ties with Antena (72)
        seed.add_product(conn, 73, "D73", "Zeta")
        seed.add_item(conn, "MLA8", status="active")
        seed.add_link(conn, "MLA8", 73)

    def ordered(then) -> list[int]:
        return [row.product_item_id for row in page(store, "unidades_30d", True, then=then, estado="active").rows]

    assert ordered(()) == [71, 70, NO_PRODUCT, 72, 73]  # the tie goes by product id
    assert ordered((("titulo", True),)) == [71, 70, NO_PRODUCT, 73, 72]
    assert ordered((("titulo", False),)) == [71, 70, NO_PRODUCT, 72, 73]
    keys = products.ordered_product_keys(
        store, parse_filter(estado="active"), "unidades_30d", True, None, then=(("titulo", True),)
    )
    store.rollback()
    assert keys == [71, 70, NO_PRODUCT, 73, 72]


def test_name_first_keeps_sin_producto_last_whatever_follows(store) -> None:
    got = page(store, "titulo", True, then=(("unidades_30d", True),), estado="active")
    assert [row.product_item_id for row in got.rows] == [71, 70, 72, NO_PRODUCT]


def test_an_unknown_next_key_is_rejected(store) -> None:
    with pytest.raises(products.FilterError):
        page(store, "titulo", False, then=(("precio", False),))


def test_an_unknown_sort_is_rejected(store) -> None:
    with pytest.raises(products.FilterError):
        page(store, "precio")


def test_a_page_past_the_end_is_empty_with_the_total(store) -> None:
    got = page(store, offset=10, estado="active")
    assert (got.rows, got.total) == ([], 4)


def test_an_empty_selection_is_empty_never_the_whole_store(store) -> None:
    got = page(store, q="MLA999")
    assert (got.rows, got.total, got.mla_count) == ([], 0, 0)


def test_one_board_for_the_whole_page_in_its_publication_view(store, monkeypatch) -> None:
    entered: list = []
    real = board.Board.__enter__
    monkeypatch.setattr(board.Board, "__enter__", lambda self: entered.append(self.f.group_by) or real(self))
    page(store, estado="active")
    assert entered == ["publication"]


def test_the_counts_follow_the_filters(store) -> None:
    every = by_product(page(store))
    assert every[70].publications_count == 3 and every[70].units == 103  # MLA3 is back
    assert (
        store.execute(
            select(func.count()).select_from(build_base_select(parse_filter(), T.i.item_id).subquery())
        ).scalar()
        == 7
    )


def test_a_link_to_a_product_missing_from_the_catalog_is_its_own_row(store) -> None:
    """The link is the truth even when its product is gone from `productos_erp`: the row is the link's product id,
    opened by `producto=<id>`, and it lists exactly what the row counts -- never folded into "Sin producto"."""
    conn = store.connection()
    seed.add_item(conn, "MLA8", status="active")
    seed.add_link(conn, "MLA8", 99)  # no product 99 in the catalog
    store.commit()
    rows = by_product(page(store, estado="active"))
    dangling = rows[99]
    assert (dangling.key, dangling.title, dangling.sku, dangling.marca) == ("99", "Producto #99", None, None)
    assert expansion(store, dangling, estado="active") == ["MLA8"]
    assert dangling.publications_count == 1
    assert "MLA8" not in expansion(store, rows[NO_PRODUCT], estado="active")
    assert rows[NO_PRODUCT].publications_count == len(expansion(store, rows[NO_PRODUCT], estado="active"))


def _more(store, *rows) -> None:
    """Extra publications for one test: (mla, product to add or None, its code, its description, link target, status)."""
    conn = store.connection()
    for mla, product, codigo, descripcion, link_to, match_status, stock in rows:
        if product is not None:
            seed.add_product(conn, product, codigo, descripcion, stock=stock)
        seed.add_item(conn, mla, status="active")
        seed.add_link(conn, mla, link_to, match_status=match_status)
    store.commit()


def test_sorted_by_name_is_by_what_the_row_shows_with_sin_producto_last(store) -> None:
    _more(
        store,
        ("MLA8", 73, "AAA-73", None, 73, "linked", None),  # no description: the row shows its code
        ("MLA9", None, None, None, 99, "linked", None),  # dangling: the row shows "Producto #99"
    )
    asc = [row.title for row in page(store, "titulo", False, estado="active").rows]
    assert asc == ["AAA-73", "Antena", "Producto #99", "Router AX", "Switch 8p", "Sin producto"]
    desc = [row.title for row in page(store, "titulo", True, estado="active").rows]
    assert desc == ["Switch 8p", "Router AX", "Producto #99", "Antena", "AAA-73", "Sin producto"]


def test_the_stock_is_the_erp_stock_of_items_only_through_a_linked_link(store) -> None:
    """Same rule as `/items` (`filters.erp_stock`): only a `linked` link gives a product its ERP stock. A conflict
    link names no product (the table's CHECK: `linked` <=> `producto_item_id` set), so its publication sits in
    "Sin producto", which has no stock -- the candidate product's stock never leaks in."""
    conn = store.connection()
    seed.add_product(conn, 74, "D74", "Mouse", stock=5)
    seed.add_item(conn, "MLA8", status="active")
    seed.add_link(conn, "MLA8", None, match_status="conflict")
    store.commit()
    rows = by_product(page(store, estado="active"))
    assert 74 not in rows
    assert rows[NO_PRODUCT].stock is None and "MLA8" in expansion(store, rows[NO_PRODUCT], estado="active")
    assert rows[70].stock == 9  # a linked link keeps it


def test_the_product_cost_is_read_only_when_asked(store) -> None:
    store.execute(text("UPDATE productos_erp SET costo = 50, moneda_costo = 'USD' WHERE item_id = 70"))
    f = parse_filter(estado="active")
    assert products.list_products(store, f, products.DEFAULT_SORT, True, 50, 0).costs == {}
    costs = products.list_products(store, f, products.DEFAULT_SORT, True, 50, 0, cost=True).costs
    store.rollback()
    assert costs["70"] == {"amount": 50.0, "currency": "USD"}
    assert costs["71"] is None and costs[str(NO_PRODUCT)] is None
