"""ODD `metricas-ml-scope-pm` T1 on real Postgres: `Board(scope_pairs=...)` bounds
the per-item base to the caller's (marca, categoría) pairs, so rows, KPIs,
facets, every group level, the export leaves and a product's publications all
see only the in-scope products. `None` = no scope, `[]` = nothing visible."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.services.ml_daily_metrics import board, groups
from tests.services.ml_daily_metrics import test_board_nested_groups_postgres as nested

# Reuse the nine-product tree of the nested-groups tests as THIS module's fixture
# (bound by name, so pytest collects it here without a shadowing import).
globals()["tree_catalog"] = nested.tree_catalog
NONE = board.NO_GROUP

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)

# tree_catalog: 21/26/27 Epson+Impresoras, 29 Logitech+Gaming, 23 HP+Impresoras,
# 22 Epson+Insumos, 24 Logitech+Perifericos, 28 Epson without categoría, 25 nothing.
EPSON_LOGI = [("EPSON", "IMPRESORAS"), ("LOGITECH", "GAMING")]
IN_SCOPE = {"21", "26", "27", "29"}
ALL_PRODUCTS = {str(n) for n in range(21, 30)}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _filter(dimension="marca", group_by="product", **filters):
    return board.BoardFilter(
        date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by=group_by, dimension=dimension, **filters
    )


def _page_keys(db, scope_pairs, **filters):
    with board.Board(db, _filter(**filters), scope_pairs=scope_pairs) as b:
        return {row.key for row in b.page(None)}


@pytest.mark.postgres
def test_rows_page_and_count_only_see_the_scoped_products(tree_catalog) -> None:
    assert _page_keys(tree_catalog, EPSON_LOGI) == IN_SCOPE
    with board.Board(tree_catalog, _filter(), scope_pairs=EPSON_LOGI) as b:
        assert b.product_count() == 4
        assert {row.key for row in b.page(2)} <= IN_SCOPE


@pytest.mark.postgres
def test_no_scope_changes_nothing_and_an_empty_scope_hides_everything(tree_catalog) -> None:
    assert _page_keys(tree_catalog, None) == ALL_PRODUCTS
    assert _page_keys(tree_catalog, []) == set()
    with board.Board(tree_catalog, _filter(), scope_pairs=[]) as b:
        k = b.kpis()
        facets = b.facets()
        assert b.product_count() == 0
    assert (k.units, k.rows, k.gross) == (0, 0, 0)
    assert facets.stores == {} and facets.stores_total == 0
    assert (facets.product.marcas, facets.product.categorias, facets.product.pms) == ([], [], [])
    assert (facets.pub_status, facets.pub_type) == ({}, {})


@pytest.mark.postgres
def test_a_pair_matches_only_as_a_pair_not_marca_and_categoria_separately(tree_catalog) -> None:
    # EPSON+GAMING and LOGITECH+IMPRESORAS exist as no product: nothing leaks in
    # from the cross product of the scoped brands and categories.
    assert _page_keys(tree_catalog, [("EPSON", "GAMING"), ("LOGITECH", "IMPRESORAS")]) == set()


@pytest.mark.postgres
def test_kpis_and_series_add_up_the_scoped_products_only(tree_catalog) -> None:
    with board.Board(tree_catalog, _filter(), scope_pairs=EPSON_LOGI) as b:
        k = b.kpis()
    # 21: 1u + 2u, 26: 2u, 27: 1u, 29: 1u
    assert (k.units, k.rows) == (7, 4)
    assert sum(k.series_units) == 7


@pytest.mark.postgres
def test_facets_list_only_options_from_scoped_products(tree_catalog) -> None:
    with board.Board(tree_catalog, _filter(), scope_pairs=[("HP", "IMPRESORAS")]) as b:
        facets = b.facets()
    p = facets.product
    assert p.marcas == ["HP"]
    assert p.categorias == ["Impresoras"]
    assert sorted(x["id"] for x in p.pms) == [902]
    assert [s["id"] for g in p.subcategorias for s in g["subcategorias"]] == [10]
    assert facets.stores == {"57997": 1}
    assert facets.stores_total == 1

    with board.Board(tree_catalog, _filter(), scope_pairs=EPSON_LOGI) as b:
        wide = b.facets().product
    assert wide.marcas == ["Epson", "Logitech"]
    assert sorted(wide.categorias) == ["Gaming", "Impresoras"]


@pytest.mark.postgres
def test_every_group_level_is_bounded_by_the_scope(tree_catalog) -> None:
    def children(path, scope_pairs=EPSON_LOGI):
        leaf = len(path) == len(groups.levels_of("marca")) - 1
        f = _filter("marca", group_by="product" if leaf else "group")
        with board.Board(tree_catalog, f, scope=path, scope_pairs=scope_pairs) as b:
            return {row.key for row in (b.page(None) if leaf else b.group_page(None))}

    assert children(()) == {"EPSON", "LOGITECH"}
    assert children(("EPSON",)) == {"IMPRESORAS"}  # no INSUMOS, no "Sin categoría"
    assert children(("LOGITECH",)) == {"GAMING"}
    assert children(("EPSON", "IMPRESORAS")) == {"10", "11", NONE}
    assert children(("EPSON", "IMPRESORAS", "10")) == {"21"}
    # A node of an out-of-scope brand opens into nothing.
    assert children(("HP",)) == set()
    assert children(("HP", "IMPRESORAS", "10")) == set()

    f = _filter("marca", group_by="group")
    with board.Board(tree_catalog, f, scope_pairs=EPSON_LOGI) as b:
        assert b.group_counts()[0] == 2
    with board.Board(tree_catalog, f, scope_pairs=[]) as b:
        assert b.group_page(None) == []
        assert b.group_counts() == (0, 0)


@pytest.mark.postgres
@pytest.mark.parametrize("dimension", ["categoria", "subcategoria", "tienda", "pm"])
def test_every_dimension_top_level_is_bounded_by_the_scope(tree_catalog, dimension) -> None:
    f = _filter(dimension, group_by="group")
    with board.Board(tree_catalog, f, scope_pairs=[("HP", "IMPRESORAS")]) as b:
        rows = b.group_page(None)
    # HP/Impresoras is product 23 (subcategoría 10, store 57997, PM 902): one node.
    assert len(rows) == 1
    assert rows[0].units == 1


@pytest.mark.postgres
def test_the_export_leaves_are_bounded_by_the_scope(tree_catalog) -> None:
    with board.Board(
        tree_catalog, _filter("marca", group_by="group"), through_leaves=True, scope_pairs=EPSON_LOGI
    ) as b:
        keys = b.leaf_keys(1000)
        rows = b.leaves_for_keys(keys)
    assert {str(r.product_item_id) for r in rows} == IN_SCOPE
    assert len(keys) == len(rows) == 4
    with board.Board(tree_catalog, _filter("marca", group_by="group"), through_leaves=True, scope_pairs=[]) as b:
        assert b.leaf_keys(1000) == []


@pytest.mark.postgres
def test_a_products_publications_respect_the_scope(tree_catalog) -> None:
    def publications(product, scope_pairs):
        f = _filter(group_by="publication")
        with board.Board(tree_catalog, f, product_item_id=product, scope_pairs=scope_pairs) as b:
            return {row.key for row in b.page(None, apply_alerts=False)}

    assert publications(21, EPSON_LOGI) == {"MLA9000000021", "MLA9000000121"}
    assert publications(23, EPSON_LOGI) == set()  # HP: out of scope
    assert publications(23, None) == {"MLA9000000023"}
    assert publications(21, []) == set()
