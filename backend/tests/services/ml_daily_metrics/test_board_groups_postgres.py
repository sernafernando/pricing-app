"""ODD `metricas-ml-vista-agrupada` T1 on real Postgres: the TOP LEVEL of the
"Agrupado" view sums the board's (product, MLA) pairs by marca, categoría,
subcategoría, tienda or PM (the deeper levels: `test_board_nested_groups_postgres`). Every dimension has its "Sin X" bucket, the stores sharing a `clave` are ONE
row, a group's markup is SUM(gauss)/SUM(costo) (never an average of
percentages), and the groups add up to the very same totals as the ungrouped KPIs."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_daily_metrics import board
from tests.services.ml_daily_metrics.test_board_postgres import _group, _order

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
NONE = board.NO_GROUP


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _publish(db, product, mla, store, mlp_id) -> None:
    db.execute(
        text(
            "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, item_id, mlp_official_store_id) "
            "VALUES (:id, :mla, :item, :store)"
        ),
        {"id": mlp_id, "mla": mla, "item": product, "store": store},
    )


def _sell(db, n, product, mla, *, qty=1, tg="10", costo="50", ago=timedelta(hours=3)) -> None:
    order_id = 2000012345678900 + n
    _order(db, order_id, [(product, mla, qty, Decimal(costo) / qty)], tg=tg, costo=costo)
    _group(db, f"o:{order_id}", [order_id], NOW - ago)


@pytest.fixture()
def catalog(board_pg):
    """Five products over the dimensions, with sales split like this:

    21 Epson/Impresoras/10 stock 5: A21 in Gauss 57997 (1u tg10/c50) and B21 in the
        OLD TP-Link store 2645 (2u tg20/c100)
    22 Epson/Insumos/20 stock 0: C22 in store 2645 (3u tg90/c100) -- 5 days ago
    23 HP/Impresoras/10 stock 7: D23 in Gauss (1u tg10/c50)
    24 Logitech/Perifericos/30 stock 2: E24 in the NEW TP-Link store 471846 (1u tg5/c50)
    25 no marca, categoría or subcategoría, no store, stock 1: F25 (1u tg1/c10)
    """
    db = board_pg
    db.execute(
        text(
            "INSERT INTO usuarios (id, nombre) VALUES (901, 'Ana'), (902, 'Beto');"
            "INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES "
            "('EPSON', 'IMPRESORAS', 901), ('Epson', 'Insumos', 901), ('HP', 'Impresoras', 902);"
            "INSERT INTO subcategorias_grupos (subcat_id, grupo_id, nombre_subcategoria, nombre_categoria) VALUES "
            "(10, 1, 'Laser', 'Impresoras'), (20, 1, 'Toner', 'Insumos'), (30, 1, 'Mouse', 'Perifericos');"
            "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden, activa) VALUES "
            "(57997, 'Gauss', NULL, 1, true), (2645, 'TP-Link vieja', 'tplink', 2, false), "
            "(471846, 'TP-Link', 'tplink', 3, true);"
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) VALUES "
            "(21, 'S21', 'Epson L3250', 'Epson', 'Impresoras', 10, 5), "
            "(22, 'S22', 'Tinta', 'EPSON', 'Insumos', 20, 0), "
            "(23, 'S23', 'HP Laser', 'HP', 'Impresoras', 10, 7), "
            "(24, 'S24', 'Mouse', 'Logitech', 'Perifericos', 30, 2), "
            "(25, 'S25', 'Cable suelto', NULL, NULL, NULL, 1);"
        )
    )
    for mlp_id, (product, mla, store) in enumerate(
        (
            (21, "MLA9000000021", 57997),
            (21, "MLA9000000121", 2645),
            (22, "MLA9000000022", 2645),
            (23, "MLA9000000023", 57997),
            (24, "MLA9000000024", 471846),
            (25, "MLA9000000025", None),
        ),
        start=9000,
    ):
        _publish(db, product, mla, store, mlp_id)
    _sell(db, 1, 21, "MLA9000000021", qty=1, tg="10", costo="50")
    _sell(db, 2, 21, "MLA9000000121", qty=2, tg="20", costo="100")
    _sell(db, 3, 22, "MLA9000000022", qty=3, tg="90", costo="100", ago=timedelta(days=5))
    _sell(db, 4, 23, "MLA9000000023", qty=1, tg="10", costo="50")
    _sell(db, 5, 24, "MLA9000000024", qty=1, tg="5", costo="50")
    _sell(db, 6, 25, "MLA9000000025", qty=1, tg="1", costo="10")
    return db


def _filter(dimension, **filters):
    return board.BoardFilter(
        date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by="group", dimension=dimension, **filters
    )


def groups(db, dimension, **filters):
    with board.Board(db, _filter(dimension, **filters), scope_pairs=None) as b:
        return {row.key: row for row in b.group_page(None)}


def kpis(db, **filters):
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, **filters)
    with board.Board(db, f, scope_pairs=None) as b:
        return b.kpis()


DIMENSIONS = ("marca", "categoria", "subcategoria", "tienda", "pm")


@pytest.mark.postgres
def test_marca_groups_case_insensitively_with_a_sin_marca_bucket(catalog) -> None:
    rows = groups(catalog, "marca")

    assert set(rows) == {"EPSON", "HP", "LOGITECH", NONE}
    assert rows["EPSON"].units == 6  # Epson + EPSON spellings are ONE brand
    assert rows[NONE].title == "Sin marca"
    assert rows[NONE].units == 1
    assert (rows["EPSON"].products_count, rows["EPSON"].publications_count) == (2, 3)


@pytest.mark.postgres
def test_markup_is_the_ratio_of_sums_never_an_average_of_percentages(catalog) -> None:
    epson = groups(catalog, "marca")["EPSON"]

    # (10 + 20 + 90) / (50 + 100 + 100) = 48.0%; the average of the three
    # orders' own percentages (20, 20, 90) would be 43.3.
    assert (epson.mtg, epson.costo) == (Decimal("120.00"), Decimal("250.00"))
    assert round(epson.markup, 1) == Decimal("48.0")


@pytest.mark.postgres
def test_a_group_without_cost_has_no_markup(board_pg) -> None:
    db = board_pg
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) "
            "VALUES (31, 'S31', 'Sin costo', 'Zeta', 'Cat', NULL, 1)"
        )
    )
    # An unresolved order: units count, Total Gauss and cost do not.
    order_id = 2000012345678990
    _order(db, order_id, [(31, "MLA9000000031", 1, 10)], tg="0", costo="0")
    db.execute(text("UPDATE ml_order_metrics SET gauss_status = 'unresolved' WHERE order_id = :o"), {"o": order_id})
    _group(db, f"o:{order_id}", [order_id], NOW - timedelta(hours=1))

    zeta = groups(db, "marca")["ZETA"]

    assert zeta.units == 1
    assert zeta.markup is None


@pytest.mark.postgres
def test_categoria_groups_with_a_sin_categoria_bucket(catalog) -> None:
    rows = groups(catalog, "categoria")

    assert set(rows) == {"IMPRESORAS", "INSUMOS", "PERIFERICOS", NONE}
    assert rows["IMPRESORAS"].units == 4  # 21 (1 + 2) and 23
    assert rows[NONE].title == "Sin categoría"


@pytest.mark.postgres
def test_subcategoria_shows_the_name_and_its_categoria_not_the_id(catalog) -> None:
    rows = groups(catalog, "subcategoria")

    # A subcategoría node is told apart by the categoría it sits in (ODD
    # `metricas-ml-agrupado-anidado`): `<id>|<categoría>`.
    assert set(rows) == {"10|IMPRESORAS", "20|INSUMOS", "30|PERIFERICOS", f"{NONE}|{NONE}"}
    assert rows["10|IMPRESORAS"].title == "Laser · Impresoras"
    assert rows["20|INSUMOS"].title == "Toner · Insumos"
    assert rows[f"{NONE}|{NONE}"].title == "Sin subcategoría · Sin categoría"


@pytest.mark.postgres
def test_a_subcategoria_missing_from_the_names_table_is_still_a_group(catalog) -> None:
    catalog.execute(text("UPDATE productos_erp SET subcategoria_id = 99 WHERE item_id = 24"))

    rows = groups(catalog, "subcategoria")

    assert rows["99|PERIFERICOS"].title == "Subcategoría #99 · Perifericos"
    assert rows["99|PERIFERICOS"].units == 1


@pytest.mark.postgres
def test_tienda_merges_the_ids_of_a_clave_into_one_row_named_after_the_active_one(catalog) -> None:
    rows = groups(catalog, "tienda")

    # 2645 (retired) + 471846 (current) share the `tplink` clave: ONE row.
    assert set(rows) == {"s:57997", "c:tplink", NONE}
    assert rows["c:tplink"].title == "TP-Link"
    assert rows["c:tplink"].units == 2 + 3 + 1  # B21 + C22 + E24
    assert rows["s:57997"].title == "Gauss"
    assert rows["s:57997"].units == 1 + 1  # A21 + D23
    assert rows[NONE].title == "Sin tienda"


@pytest.mark.postgres
def test_a_store_without_a_row_in_the_names_table_reads_tienda_id(catalog) -> None:
    _publish(catalog, 25, "MLA9000000099", 777, 9100)
    _sell(catalog, 9, 25, "MLA9000000099", qty=1, tg="1", costo="10")

    rows = groups(catalog, "tienda")

    assert rows["s:777"].title == "Tienda 777"


@pytest.mark.postgres
def test_a_product_selling_in_two_stores_contributes_only_what_each_store_sold(catalog) -> None:
    rows = groups(catalog, "tienda")

    # Product 21 sold 1u in Gauss and 2u in TP-Link: each store gets ITS part.
    assert rows["s:57997"].units == 2 and rows["s:57997"].publications_count == 2
    assert rows["c:tplink"].publications_count == 3
    assert rows["s:57997"].gross + rows["c:tplink"].gross + rows[NONE].gross == kpis(catalog).gross


@pytest.mark.postgres
def test_pm_groups_by_the_marca_categoria_pair_with_a_sin_pm_bucket(catalog) -> None:
    rows = groups(catalog, "pm")

    assert set(rows) == {"901", "902", NONE}
    assert rows["901"].title == "Ana"
    assert rows["901"].units == 1 + 2 + 3  # Epson/Impresoras (case-insensitive) + Epson/Insumos
    assert rows["902"].title == "Beto"
    assert rows[NONE].title == "Sin PM"
    assert rows[NONE].units == 2  # Logitech (no pair) + the product with no marca


@pytest.mark.postgres
def test_two_marcas_pm_rows_differing_only_in_case_never_double_count(catalog) -> None:
    catalog.execute(text("INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES ('epson', 'impresoras', 902)"))

    rows = groups(catalog, "pm")

    assert sum(row.units for row in rows.values()) == kpis(catalog).units


@pytest.mark.postgres
@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_the_groups_add_up_to_the_ungrouped_totals(catalog, dimension) -> None:
    rows = groups(catalog, dimension).values()
    k = kpis(catalog)

    assert sum(r.units for r in rows) == k.units == 9
    assert sum(r.gross for r in rows) == k.gross
    assert sum(r.tg for r in rows) == k.tg
    assert sum(r.mtg for r in rows) == k.mtg
    assert sum(r.costo for r in rows) == k.costo
    # And the windows add up too.
    assert sum(r.windows["30d"] for r in rows) == sum(row.windows["30d"] for row in _products(catalog))


def _products(db):
    with board.Board(db, board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY), scope_pairs=None) as b:
        return b.page(None)


@pytest.mark.postgres
@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_row_filters_are_decided_per_product_before_grouping(catalog, dimension) -> None:
    kept = groups(catalog, dimension, stock=("con_stock",))  # 22 has stock 0

    assert sum(r.units for r in kept.values()) == kpis(catalog, stock=("con_stock",)).units == 6
    # A product enters a group only if it passes the row filters: the 3 units
    # of product 22 (no stock) are in no group.
    assert "INSUMOS" not in groups(catalog, "categoria", stock=("con_stock",))


@pytest.mark.postgres
def test_pair_filters_narrow_the_groups(catalog) -> None:
    rows = groups(catalog, "marca", stores=("57997",))

    assert set(rows) == {"EPSON", "HP"}
    assert rows["EPSON"].units == 1  # only A21 is in Gauss


@pytest.mark.postgres
def test_solo_con_ventas_drops_groups_with_no_units_in_the_period(catalog) -> None:
    catalog.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) "
            "VALUES (41, 'S41', 'Nunca vendido', 'Quieta', 'Cat', NULL, 1)"
        )
    )
    _publish(catalog, 41, "MLA9000000041", 57997, 9200)

    assert "QUIETA" in groups(catalog, "marca")
    assert "QUIETA" not in groups(catalog, "marca", solo_con_ventas=True)


@pytest.mark.postgres
def test_stock_adds_each_product_once_per_group(catalog) -> None:
    rows = groups(catalog, "marca")

    # Epson: product 21 (stock 5, TWO publications) + product 22 (stock 0) = 5, not 10.
    assert rows["EPSON"].stock == 5
    assert rows[NONE].stock == 1
    assert groups(catalog, "tienda")["s:57997"].stock == 5 + 7  # products 21 and 23


@pytest.mark.postgres
def test_last_sale_and_ageing_are_the_groups_most_recent_sale(catalog) -> None:
    rows = groups(catalog, "categoria")

    assert rows["IMPRESORAS"].ageing_days == 0
    assert rows["INSUMOS"].ageing_days == 5  # product 22 sold 5 days ago
    assert rows["INSUMOS"].last_sale_at is not None


@pytest.mark.postgres
def test_series_of_a_group_add_up_to_its_units(catalog) -> None:
    epson = groups(catalog, "marca")["EPSON"]

    assert len(epson.series_units) == board.SERIES_DAYS
    assert sum(epson.series_units) == epson.units
    assert [m for m in epson.series_markup if m is not None]


@pytest.mark.postgres
@pytest.mark.parametrize(
    "sort, desc, first",
    [("units", True, "EPSON"), ("units", False, "HP"), ("title", False, "EPSON"), ("markup", True, "EPSON")],
)
def test_groups_sort_by_the_board_columns(catalog, sort, desc, first) -> None:
    with board.Board(catalog, _filter("marca", sort=sort, sort_desc=desc), scope_pairs=None) as b:
        keys = [row.key for row in b.group_page(None)]

    assert keys[0] == first


@pytest.mark.postgres
def test_pages_cover_every_group_once(catalog) -> None:
    with board.Board(catalog, _filter("marca"), scope_pairs=None) as b:
        first = [r.key for r in b.group_page(2, 0)]
        second = [r.key for r in b.group_page(2, 2)]
        everything = [r.key for r in b.group_page(None)]

    assert first + second == everything and len(set(everything)) == len(everything) == 4
