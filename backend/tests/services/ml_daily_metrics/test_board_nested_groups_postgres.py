"""ODD `metricas-ml-agrupado-anidado` T1 on real Postgres: the "Agrupado" view is
a TREE. Each dimension opens level by level down to the products (categoría >
subcategoría > producto; marca > categoría > subcategoría > producto; PM and
tienda in front of that), a node is identified by the PATH of its ancestors'
keys, every level has its "Sin X" bucket, and the children of a node add up to
the node."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_daily_metrics import board, groups
from tests.services.ml_daily_metrics.test_board_postgres import _group, _order

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
NONE = board.NO_GROUP
DIMENSIONS = ("marca", "categoria", "subcategoria", "tienda", "pm")


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
def tree_catalog(board_pg):
    """Nine products over the tree:

    21 Epson/Impresoras/10 Laser: Gauss 1u + old TP-Link 2u
    22 EPSON/Insumos/20 Toner: old TP-Link 3u (5 days ago), stock 0
    23 HP/Impresoras/10: Gauss 1u
    24 Logitech/Perifericos/30 Mouse: new TP-Link 1u
    25 nothing at all (no marca, categoría, subcategoría, store)
    26 Epson/Impresoras/11 Tinta continua: Gauss 2u
    27 Epson/Impresoras/no subcategoría: Gauss 1u
    28 Epson/no categoría/no subcategoría: Gauss 1u
    29 Logitech/Gaming/30 Mouse: new TP-Link 1u  (subcategoría 30 under TWO categorías)
    """
    db = board_pg
    db.execute(
        text(
            "INSERT INTO usuarios (id, nombre) VALUES (901, 'Ana'), (902, 'Beto');"
            "INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES "
            "('EPSON', 'IMPRESORAS', 901), ('Epson', 'Insumos', 901), ('HP', 'Impresoras', 902), "
            "('Logitech', 'Gaming', 902);"
            "INSERT INTO subcategorias_grupos (subcat_id, grupo_id, nombre_subcategoria, nombre_categoria) VALUES "
            "(10, 1, 'Laser', 'Impresoras'), (11, 1, 'Tinta continua', 'Impresoras'), (20, 1, 'Toner', 'Insumos'), "
            "(30, 1, 'Mouse', 'Perifericos');"
            "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden, activa) VALUES "
            "(57997, 'Gauss', NULL, 1, true), (2645, 'TP-Link vieja', 'tplink', 2, false), "
            "(471846, 'TP-Link', 'tplink', 3, true);"
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) VALUES "
            "(21, 'S21', 'Epson L3250', 'Epson', 'Impresoras', 10, 5), "
            "(22, 'S22', 'Tinta', 'EPSON', 'Insumos', 20, 0), "
            "(23, 'S23', 'HP Laser', 'HP', 'Impresoras', 10, 7), "
            "(24, 'S24', 'Mouse', 'Logitech', 'Perifericos', 30, 2), "
            "(25, 'S25', 'Cable suelto', NULL, NULL, NULL, 1), "
            "(26, 'S26', 'Epson EcoTank', 'Epson', 'Impresoras', 11, 3), "
            "(27, 'S27', 'Epson sin sub', 'Epson', 'Impresoras', NULL, 4), "
            "(28, 'S28', 'Epson sin cat', 'Epson', NULL, NULL, 2), "
            "(29, 'S29', 'Mouse gamer', 'Logitech', 'Gaming', 30, 1);"
        )
    )
    publications = (
        (21, "MLA9000000021", 57997),
        (21, "MLA9000000121", 2645),
        (22, "MLA9000000022", 2645),
        (23, "MLA9000000023", 57997),
        (24, "MLA9000000024", 471846),
        (25, "MLA9000000025", None),
        (26, "MLA9000000026", 57997),
        (27, "MLA9000000027", 57997),
        (28, "MLA9000000028", 57997),
        (29, "MLA9000000029", 471846),
    )
    for mlp_id, (product, mla, store) in enumerate(publications, start=9000):
        _publish(db, product, mla, store, mlp_id)
    _sell(db, 1, 21, "MLA9000000021", qty=1, tg="10", costo="50")
    _sell(db, 2, 21, "MLA9000000121", qty=2, tg="20", costo="100")
    _sell(db, 3, 22, "MLA9000000022", qty=3, tg="90", costo="100", ago=timedelta(days=5))
    _sell(db, 4, 23, "MLA9000000023", qty=1, tg="10", costo="50")
    _sell(db, 5, 24, "MLA9000000024", qty=1, tg="5", costo="50")
    _sell(db, 6, 25, "MLA9000000025", qty=1, tg="1", costo="10")
    _sell(db, 7, 26, "MLA9000000026", qty=2, tg="20", costo="80")
    _sell(db, 8, 27, "MLA9000000027", qty=1, tg="7", costo="30")
    _sell(db, 9, 28, "MLA9000000028", qty=1, tg="3", costo="20")
    _sell(db, 10, 29, "MLA9000000029", qty=1, tg="4", costo="40")
    return db


def _filter(dimension, group_by="group", **filters):
    return board.BoardFilter(
        date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by=group_by, dimension=dimension, **filters
    )


def children(db, dimension, scope=(), **filters):
    """The rows one level below `scope`: nodes, or products at the last level."""
    leaf = len(scope) == len(groups.levels_of(dimension)) - 1
    f = _filter(dimension, group_by="product" if leaf else "group", **filters)
    with board.Board(db, f, scope=scope) as b:
        return {row.key: row for row in (b.page(None) if leaf else b.group_page(None))}


def kpis(db, **filters):
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, **filters)
    with board.Board(db, f) as b:
        return b.kpis()


def walk(db, dimension, scope=(), **filters):
    """Yield `(path, node, rows_below)` for every NODE of the tree, depth first
    (the products below the last level are the leaves, not nodes)."""
    if len(scope) >= len(groups.levels_of(dimension)) - 1:
        return
    for key, row in children(db, dimension, scope, **filters).items():
        path = (*scope, key)
        yield path, row, children(db, dimension, path, **filters)
        yield from walk(db, dimension, path, **filters)


# ── the hierarchy table ──────────────────────────────────────────


@pytest.mark.parametrize(
    "dimension, levels",
    [
        ("categoria", ("categoria", "subcategoria", "product")),
        ("subcategoria", ("subcategoria_categoria", "product")),
        ("marca", ("marca", "categoria", "subcategoria", "product")),
        ("pm", ("pm", "marca", "categoria", "subcategoria", "product")),
        ("tienda", ("tienda", "marca", "categoria", "subcategoria", "product")),
    ],
)
def test_each_dimension_has_the_confirmed_levels(dimension, levels) -> None:
    assert groups.levels_of(dimension) == levels


def test_every_dimension_has_a_hierarchy() -> None:
    assert set(groups.HIERARCHIES) == set(groups.DIMENSIONS)


# ── nodes at every depth ─────────────────────────────────────────


@pytest.mark.postgres
def test_a_categoria_opens_into_its_subcategorias_with_a_sin_subcategoria_bucket(tree_catalog) -> None:
    subs = children(tree_catalog, "categoria", ("IMPRESORAS",))

    assert set(subs) == {"10", "11", NONE}
    assert subs["10"].title == "Laser"
    assert subs["11"].title == "Tinta continua"
    assert subs[NONE].title == "Sin subcategoría"
    assert subs["10"].units == 1 + 2 + 1  # products 21 and 23
    assert subs[NONE].units == 1  # product 27


@pytest.mark.postgres
def test_a_subcategoria_opens_into_its_products(tree_catalog) -> None:
    products = children(tree_catalog, "categoria", ("IMPRESORAS", "10"))

    assert set(products) == {"21", "23"}
    assert products["21"].units == 3


@pytest.mark.postgres
def test_sin_categoria_opens_into_its_own_sin_subcategoria(tree_catalog) -> None:
    subs = children(tree_catalog, "categoria", (NONE,))

    assert set(subs) == {NONE}  # products 25 and 28 have no subcategoría either
    assert subs[NONE].units == 2
    assert set(children(tree_catalog, "categoria", (NONE, NONE))) == {"25", "28"}


@pytest.mark.postgres
def test_marca_opens_into_categorias_then_subcategorias_then_products(tree_catalog) -> None:
    categorias = children(tree_catalog, "marca", ("EPSON",))
    assert set(categorias) == {"IMPRESORAS", "INSUMOS", NONE}
    assert categorias[NONE].title == "Sin categoría"

    subs = children(tree_catalog, "marca", ("EPSON", "IMPRESORAS"))
    assert set(subs) == {"10", "11", NONE}
    assert subs[NONE].title == "Sin subcategoría"

    assert set(children(tree_catalog, "marca", ("EPSON", "IMPRESORAS", "10"))) == {"21"}
    assert set(children(tree_catalog, "marca", ("EPSON", NONE, NONE))) == {"28"}


@pytest.mark.postgres
def test_pm_opens_into_marcas_categorias_subcategorias_products(tree_catalog) -> None:
    assert set(children(tree_catalog, "pm")) == {"901", "902", NONE}
    marcas = children(tree_catalog, "pm", ("901",))
    assert set(marcas) == {"EPSON"}
    assert set(children(tree_catalog, "pm", ("901", "EPSON"))) == {"IMPRESORAS", "INSUMOS"}
    assert set(children(tree_catalog, "pm", ("901", "EPSON", "IMPRESORAS"))) == {"10", "11", NONE}
    assert set(children(tree_catalog, "pm", ("901", "EPSON", "IMPRESORAS", "11"))) == {"26"}
    # Epson without a categoría has no (marca, categoría) pair: it is under "Sin PM".
    assert set(children(tree_catalog, "pm", (NONE, "EPSON"))) == {NONE}


@pytest.mark.postgres
def test_tienda_opens_into_marcas_and_keeps_the_clave_grouping(tree_catalog) -> None:
    assert set(children(tree_catalog, "tienda")) == {"s:57997", "c:tplink", NONE}
    marcas = children(tree_catalog, "tienda", ("c:tplink",))
    assert set(marcas) == {"EPSON", "LOGITECH"}  # the old AND the new TP-Link store, ONE node
    assert marcas["EPSON"].units == 2 + 3
    assert set(children(tree_catalog, "tienda", ("c:tplink", "EPSON", "IMPRESORAS", "10"))) == {"21"}


@pytest.mark.postgres
def test_a_product_selling_in_two_stores_keeps_only_each_stores_sales_down_the_tree(tree_catalog) -> None:
    gauss = children(tree_catalog, "tienda", ("s:57997", "EPSON", "IMPRESORAS", "10"))
    tplink = children(tree_catalog, "tienda", ("c:tplink", "EPSON", "IMPRESORAS", "10"))

    assert gauss["21"].units == 1 and gauss["21"].publications_count == 1
    assert tplink["21"].units == 2 and tplink["21"].publications_count == 1
    # Gauss' Epson holds only what Gauss sold (21: 1, 26: 2, 27: 1, 28: 1), not the TP-Link units.
    assert children(tree_catalog, "tienda", ("s:57997",))["EPSON"].units == 1 + 2 + 1 + 1


@pytest.mark.postgres
def test_subcategoria_is_labelled_with_its_categoria_and_split_per_categoria(tree_catalog) -> None:
    top = children(tree_catalog, "subcategoria")

    assert top["10|IMPRESORAS"].title == "Laser · Impresoras"
    assert top["11|IMPRESORAS"].title == "Tinta continua · Impresoras"
    # The same subcategoría under two categorías is TWO nodes.
    assert top["30|PERIFERICOS"].title == "Mouse · Perifericos"
    assert top["30|GAMING"].title == "Mouse · Gaming"
    assert top[f"{NONE}|IMPRESORAS"].title == "Sin subcategoría · Impresoras"
    assert top[f"{NONE}|{NONE}"].title == "Sin subcategoría · Sin categoría"
    assert top["10|IMPRESORAS"].units == 4
    assert set(children(tree_catalog, "subcategoria", ("30|GAMING",))) == {"29"}
    assert set(children(tree_catalog, "subcategoria", (f"{NONE}|{NONE}",))) == {"25", "28"}


@pytest.mark.postgres
def test_nodes_know_their_level_and_what_they_open_into(tree_catalog) -> None:
    top = children(tree_catalog, "marca")["EPSON"]
    assert (top.level, top.child_level) == ("marca", "categoria")
    sub = children(tree_catalog, "marca", ("EPSON", "IMPRESORAS"))["10"]
    assert (sub.level, sub.child_level) == ("subcategoria", "product")


@pytest.mark.postgres
def test_a_wrong_depth_is_refused(tree_catalog) -> None:
    with pytest.raises(ValueError):
        board.Board(tree_catalog, _filter("categoria"), scope=("A", "B", "C"))


# ── the tree adds up ─────────────────────────────────────────────


@pytest.mark.postgres
@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_the_children_of_every_node_add_up_to_the_node(tree_catalog, dimension) -> None:
    visited = 0
    for path, row, below in walk(tree_catalog, dimension):
        visited += 1
        assert sum(c.units for c in below.values()) == row.units, path
        assert sum(c.gross for c in below.values()) == row.gross, path
        assert sum(c.costo for c in below.values()) == row.costo, path
        assert abs(sum(c.tg for c in below.values()) - row.tg) <= Decimal("0.01") * len(below), path
        assert abs(sum(c.mtg for c in below.values()) - row.mtg) <= Decimal("0.01") * len(below), path
        assert sum(c.windows["30d"] for c in below.values()) == row.windows["30d"], path
        assert sum(c.publications_count for c in below.values()) == row.publications_count, path
        assert sum(c.stock or 0 for c in below.values()) == (row.stock or 0), path
        if row.child_level != "product":
            assert sum(c.products_count for c in below.values()) == row.products_count, path
        else:
            assert len(below) == row.products_count, path
    assert visited >= 3


@pytest.mark.postgres
@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_the_top_level_adds_up_to_the_ungrouped_kpis(tree_catalog, dimension) -> None:
    top = children(tree_catalog, dimension).values()
    k = kpis(tree_catalog)

    assert sum(r.units for r in top) == k.units == 14
    assert sum(r.gross for r in top) == k.gross
    assert sum(r.costo for r in top) == k.costo


@pytest.mark.postgres
def test_a_node_markup_is_the_ratio_of_its_sums_at_every_level(tree_catalog) -> None:
    node = children(tree_catalog, "marca", ("EPSON",))["IMPRESORAS"]

    # Epson/Impresoras: products 21 (30/150), 26 (20/80), 27 (7/30) -> 57/260.
    assert (node.mtg, node.costo) == (Decimal("57.00"), Decimal("260.00"))
    assert round(node.markup, 2) == round(Decimal("57") * 100 / Decimal("260"), 2)


@pytest.mark.postgres
def test_a_node_series_add_up_to_its_units(tree_catalog) -> None:
    node = children(tree_catalog, "categoria", ("IMPRESORAS",))["10"]

    assert sum(node.series_units) == node.units == 4


# ── search, filters and order apply before aggregating ───────────


@pytest.mark.postgres
def test_searching_leaves_only_the_branches_with_matching_products(tree_catalog) -> None:
    top = children(tree_catalog, "categoria", q="mouse")

    assert set(top) == {"PERIFERICOS", "GAMING"}
    assert set(children(tree_catalog, "categoria", ("GAMING",), q="mouse")) == {"30"}
    assert set(children(tree_catalog, "categoria", ("GAMING", "30"), q="mouse")) == {"29"}
    assert set(children(tree_catalog, "marca", q="mouse")) == {"LOGITECH"}
    assert set(children(tree_catalog, "tienda", ("c:tplink",), q="mouse")) == {"LOGITECH"}
    assert set(children(tree_catalog, "subcategoria", q="mouse")) == {"30|PERIFERICOS", "30|GAMING"}


@pytest.mark.postgres
def test_pair_filters_narrow_every_level(tree_catalog) -> None:
    only_gauss = children(tree_catalog, "marca", ("EPSON", "IMPRESORAS", "10"), stores=("57997",))

    assert {key: row.units for key, row in only_gauss.items()} == {"21": 1}


@pytest.mark.postgres
def test_row_filters_are_decided_per_product_at_every_level(tree_catalog) -> None:
    # Product 22 (Toner) has no stock: its branch disappears at every level.
    assert set(children(tree_catalog, "marca", ("EPSON",), stock=("con_stock",))) == {"IMPRESORAS", NONE}
    assert "INSUMOS" not in children(tree_catalog, "categoria", stock=("con_stock",))
    assert "20" not in children(tree_catalog, "categoria", ("INSUMOS",), stock=("con_stock",))
    # A product that stays keeps ALL of its sales (21: 1 + 2 units), the filter is per product.
    assert children(tree_catalog, "marca", ("EPSON", "IMPRESORAS", "10"), stock=("con_stock",))["21"].units == 3


@pytest.mark.postgres
def test_solo_con_ventas_hides_a_node_with_no_units_in_the_period(tree_catalog) -> None:
    db = tree_catalog
    # Product 30 sells only in the new TP-Link store; its Gauss publication never sold.
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) "
            "VALUES (30, 'S30', 'Zeta', 'Zeta', 'Impresoras', 10, 1)"
        )
    )
    _publish(db, 30, "MLA9000000030", 57997, 9100)
    _publish(db, 30, "MLA9000000130", 471846, 9101)
    _sell(db, 11, 30, "MLA9000000130", qty=1, tg="2", costo="20")

    assert "ZETA" in children(db, "tienda", ("s:57997",))
    assert "ZETA" not in children(db, "tienda", ("s:57997",), solo_con_ventas=True)
    assert "ZETA" in children(db, "tienda", ("c:tplink",), solo_con_ventas=True)


@pytest.mark.postgres
@pytest.mark.parametrize("desc, expected", [(True, ["10", "11", NONE]), (False, [NONE, "11", "10"])])
def test_the_sort_applies_inside_every_level(tree_catalog, desc, expected) -> None:
    with board.Board(tree_catalog, _filter("marca", sort="units", sort_desc=desc), scope=("EPSON", "IMPRESORAS")) as b:
        keys = [row.key for row in b.group_page(None)]

    assert keys == expected  # 10: 3 units, 11: 2, none: 1


@pytest.mark.postgres
def test_pages_of_a_nested_level_cover_every_node_once_even_with_ties(tree_catalog) -> None:
    f = _filter("subcategoria", sort="units", sort_desc=True)
    with board.Board(tree_catalog, f) as b:
        everything = [r.key for r in b.group_page(None)]
        pages = [[r.key for r in b.group_page(1, offset)] for offset in range(len(everything))]
        total, with_sales = b.group_counts()

    assert [page[0] for page in pages] == everything
    assert len(set(everything)) == len(everything) == total == 7
    assert with_sales == 7


@pytest.mark.postgres
def test_the_count_of_a_nested_level_is_that_levels(tree_catalog) -> None:
    with board.Board(tree_catalog, _filter("marca"), scope=("EPSON",)) as b:
        assert b.group_counts()[0] == 3


@pytest.mark.postgres
def test_a_product_leaf_pages_and_counts_like_the_other_levels(tree_catalog) -> None:
    f = _filter("categoria", group_by="product")
    with board.Board(tree_catalog, f, scope=("IMPRESORAS", NONE)) as b:
        assert b.product_count() == 1
        assert [r.key for r in b.page(10)] == ["27"]


@pytest.mark.postgres
def test_an_unknown_path_opens_into_nothing(tree_catalog) -> None:
    assert children(tree_catalog, "marca", ("NO-SUCH", "X")) == {}
    assert children(tree_catalog, "marca", ("EPSON", "NO-SUCH", "X")) == {}


# ── T2: one row per leaf product, with its full path (the CSV export) ──


def leaves(db, dimension, **filters):
    with board.Board(db, _filter(dimension, **filters), through_leaves=True) as b:
        keys = b.leaf_keys(1000)
        return keys, b.leaves_for_keys(keys)


@pytest.mark.postgres
def test_the_leaves_are_the_products_of_every_path_with_the_names_of_its_levels(tree_catalog) -> None:
    keys, rows = leaves(tree_catalog, "categoria")

    by_path = {tuple(row.path): row for row in rows}
    assert ("Impresoras", "Laser") in {path[:2] for path in by_path}
    laser = [row for row in rows if row.path == ["Impresoras", "Laser"]]
    assert {row.product_item_id for row in laser} == {21, 23}
    assert {row.sku for row in laser} == {"S21", "S23"}
    assert all(row.level == "product" for row in rows)
    assert len(keys) == len(rows) == 9  # every product sits under exactly one (categoría, subcategoría)


@pytest.mark.postgres
@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_the_leaves_add_up_to_the_ungrouped_totals(tree_catalog, dimension) -> None:
    _, rows = leaves(tree_catalog, dimension)
    k = kpis(tree_catalog)

    assert sum(r.units for r in rows) == k.units == 14
    assert sum(r.gross for r in rows) == k.gross
    assert sum(r.costo for r in rows) == k.costo
    assert all(len(r.path) == len(groups.levels_of(dimension)) - 1 for r in rows)


@pytest.mark.postgres
def test_a_product_in_two_stores_is_one_leaf_per_store_with_its_own_sales(tree_catalog) -> None:
    _, rows = leaves(tree_catalog, "tienda")

    own = {tuple(r.path[:1]): r.units for r in rows if r.product_item_id == 21}
    assert own == {("Gauss",): 1, ("TP-Link",): 2}


@pytest.mark.postgres
def test_the_leaves_come_in_path_order_then_the_board_sort(tree_catalog) -> None:
    _, rows = leaves(tree_catalog, "categoria", sort="units", sort_desc=True)

    paths = [tuple(r.path) for r in rows]
    assert paths == sorted(paths, key=lambda p: tuple(x.lower() for x in p))
    laser = [r.product_item_id for r in rows if r.path == ["Impresoras", "Laser"]]
    assert laser == [21, 23]  # 3 units before 1


@pytest.mark.postgres
def test_leaves_are_fetched_by_key_in_the_order_given_skipping_the_vanished(tree_catalog) -> None:
    with board.Board(tree_catalog, _filter("marca"), through_leaves=True) as b:
        keys = b.leaf_keys(1000)
        reversed_rows = b.leaves_for_keys(list(reversed(keys)))
        with_a_ghost = b.leaves_for_keys([("NO", "SUCH", "ONE", "1"), keys[0]])

    assert [(r.path, r.product_item_id) for r in reversed_rows] == [
        (r.path, r.product_item_id) for r in reversed(b_rows(tree_catalog, "marca", keys))
    ]
    assert len(with_a_ghost) == 1


def b_rows(db, dimension, keys):
    with board.Board(db, _filter(dimension), through_leaves=True) as b:
        return b.leaves_for_keys(keys)


@pytest.mark.postgres
def test_leaf_keys_are_capped(tree_catalog) -> None:
    with board.Board(tree_catalog, _filter("marca"), through_leaves=True) as b:
        assert len(b.leaf_keys(4)) == 4


@pytest.mark.postgres
def test_the_leaves_follow_the_filters_and_solo_con_ventas(tree_catalog) -> None:
    db = tree_catalog
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) "
            "VALUES (30, 'S30', 'Zeta', 'Zeta', 'Impresoras', 10, 1)"
        )
    )
    _publish(db, 30, "MLA9000000030", 57997, 9100)
    _publish(db, 30, "MLA9000000130", 471846, 9101)
    _sell(db, 11, 30, "MLA9000000130", qty=1, tg="2", costo="20")

    _, everything = leaves(db, "tienda")
    _, sold = leaves(db, "tienda", solo_con_ventas=True)
    _, mouse = leaves(db, "tienda", q="mouse")

    assert (("Gauss", "Zeta") in {tuple(r.path[:2]) for r in everything}) is True
    assert ("Gauss", "Zeta") not in {tuple(r.path[:2]) for r in sold}  # zero units in that store
    assert {r.product_item_id for r in mouse} == {24, 29}


@pytest.mark.postgres
def test_row_filters_decide_which_products_have_leaves(tree_catalog) -> None:
    _, rows = leaves(tree_catalog, "marca", stock=("con_stock",))

    assert 22 not in {r.product_item_id for r in rows}


# ── statements per request ───────────────────────────────────────


class _Count:
    def __init__(self, db) -> None:
        self.n = 0
        self.connection = db.connection()

    def __enter__(self):
        from sqlalchemy import event

        self._event = event
        event.listen(self.connection, "before_cursor_execute", self._tick)
        return self

    def __exit__(self, *exc) -> None:
        self._event.remove(self.connection, "before_cursor_execute", self._tick)

    def _tick(self, *args) -> None:
        self.n += 1


@pytest.mark.postgres
@pytest.mark.parametrize(
    "dimension, scope",
    [
        ("tienda", ()),
        ("tienda", ("c:tplink",)),
        ("tienda", ("c:tplink", "EPSON")),
        ("tienda", ("c:tplink", "EPSON", "IMPRESORAS")),
        ("tienda", ("c:tplink", "EPSON", "IMPRESORAS", "10")),
        ("categoria", ("IMPRESORAS",)),
    ],
)
@pytest.mark.parametrize("filters", [{}, {"stock": ("con_stock",), "solo_con_ventas": True}], ids=["plain", "rows"])
def test_a_level_page_costs_a_fixed_number_of_statements_at_every_depth(
    tree_catalog, dimension, scope, filters
) -> None:
    leaf = len(scope) == len(groups.levels_of(dimension)) - 1
    f = _filter(dimension, group_by="product" if leaf else "group", **filters)
    with _Count(tree_catalog) as count:
        with board.Board(tree_catalog, f, scope=scope) as b:
            if leaf:
                b.product_count()
                b.page(100, 0)
            else:
                b.group_counts()
                b.group_page(100, 0)

    # savepoint + 2 CREATE + 2 ANALYZE + count + page (+ series | details + series) + rollback.
    assert count.n <= 12, count.n
