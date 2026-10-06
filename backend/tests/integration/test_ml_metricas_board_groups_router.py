"""ODD `metricas-ml-vista-agrupada` T3 and `metricas-ml-agrupado-anidado` T3:
`GET /api/ml-metricas/board?group_by=group` (the top level of the "Agrupado"
tree), `GET /board/group-nodes?path=` (the level below a node, or its products
at the last level) and the grouped CSV (one row per product with its path).
Same data, clock and permissions as the board's router tests (`board_data`:
products 11 Epson, 12 Lenovo, 13 DeWalt, 14 TP-Link, all in categoría "Cat";
subcategoría 1 except Lenovo's 2; stores 57997, 2645, 144)."""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import csv
import io
import json
from datetime import date

from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.producto import ProductoERP
from app.routers import ml_metricas
from app.services.ml_daily_metrics import board, groups
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    SOLO_CON_VENTAS,
    _day,
    _frozen_clock,
    _grant,
    _pub,
    bg_sessions,
    board_data,
)

GROUP = {"group_by": "group", "dimension": "marca"}
NODES = f"{URL}/group-nodes"


def _path(*keys):
    return json.dumps(list(keys))


def _get(client, headers, url=URL, **params):
    resp = client.get(url, params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_key(body):
    return {row["key"]: row for row in body["rows"]}


def _csv(resp):
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))


class TestGroupedBoard:
    def test_one_row_per_marca_with_the_ratio_markup(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, **GROUP)

        assert body["group_by"] == "group" and body["dimension"] == "marca"
        rows = _by_key(body)
        assert set(rows) == {"EPSON", "LENOVO", "DEWALT", "TP-LINK"}
        epson = rows["EPSON"]
        assert epson["title"] == "Epson"
        assert (epson["units"], epson["gross"], epson["total_gauss"]) == (6, 600, 100)
        assert epson["markup_pct"] == 25.0 and epson["markup_prev_pct"] == 20.0
        assert (epson["products_count"], epson["publications_count"]) == (1, 2)
        assert epson["units_3d"] == 2 and len(epson["series_units_90d"]) == 90
        assert epson["ageing_days"] == 0 and epson["last_sale_at"].startswith("2026-09-30")

    def test_rows_say_which_level_they_are_and_what_they_open_into(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, **GROUP)

        assert body["levels"] == ["marca", "categoria", "subcategoria", "product"]
        assert {(r["level"], r["child_level"]) for r in body["rows"]} == {("marca", "categoria")}
        by_dimension = {
            dimension: _get(client, admin_auth_headers, group_by="group", dimension=dimension)["levels"]
            for dimension in ("categoria", "subcategoria", "pm", "tienda")
        }
        assert by_dimension == {
            "categoria": ["categoria", "subcategoria", "product"],
            "subcategoria": ["subcategoria_categoria", "product"],
            "pm": ["pm", "marca", "categoria", "subcategoria", "product"],
            "tienda": ["tienda", "marca", "categoria", "subcategoria", "product"],
        }

    def test_the_groups_add_up_to_the_kpis_under_the_same_filters(self, client, admin_auth_headers, board_data):
        for extra in ({}, {"stores": "57997"}, SOLO_CON_VENTAS):
            for dimension in ("marca", "categoria", "subcategoria", "tienda", "pm"):
                body = _get(client, admin_auth_headers, group_by="group", dimension=dimension, **extra)
                kpis = body["kpis"]

                assert sum(r["units"] for r in body["rows"]) == kpis["units"]["value"], (dimension, extra)
                assert round(sum(r["gross"] for r in body["rows"]), 2) == kpis["gross"]["value"], (dimension, extra)
                assert round(sum(r["total_gauss"] for r in body["rows"]), 2) == kpis["total_gauss"]["value"]

    def test_total_and_rotation_count_groups_not_products(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, dimension="tienda", group_by="group")

        # Stores 57997 (p11, p13), 2645 (p12: last sale in July) and 144 (p14).
        assert body["total"] == 3 == len(body["rows"])
        assert body["with_sales_count"] == 2
        assert body["kpis"]["rows_with_sales"] == {"value": 2, "of_total": 3}

    def test_tienda_uses_the_names_and_merges_a_clave(self, db, client, admin_auth_headers, board_data):
        db.add_all(
            [
                MlTiendaOficial(store_id=57997, nombre="Gauss", orden=1, activa=True),
                MlTiendaOficial(store_id=2645, nombre="TP-Link vieja", clave="tplink", orden=2, activa=False),
                MlTiendaOficial(store_id=144, nombre="TP-Link", clave="tplink", orden=3, activa=True),
            ]
        )
        db.commit()

        rows = _by_key(_get(client, admin_auth_headers, group_by="group", dimension="tienda"))

        assert set(rows) == {"s:57997", "c:tplink"}
        assert rows["c:tplink"]["title"] == "TP-Link"
        # p12 (store 2645) sold nothing in the period; p14 (store 144) sold 1.
        assert rows["c:tplink"]["units"] == 1 and rows["s:57997"]["units"] == 6

    def test_the_filters_apply_before_grouping(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, marcas="Epson,Lenovo", **GROUP)

        assert set(_by_key(body)) == {"EPSON", "LENOVO"}

    def test_sorting_by_a_column_and_paging(self, client, admin_auth_headers, board_data):
        by_title = _get(client, admin_auth_headers, sort="title", sort_dir="asc", **GROUP)
        assert [r["title"] for r in by_title["rows"]] == ["DeWalt", "Epson", "Lenovo", "TP-Link"]

        page = _get(client, admin_auth_headers, sort="units", sort_dir="desc", limit=1, offset=1, **GROUP)
        assert page["total"] == 4 and [r["key"] for r in page["rows"]] == ["TP-LINK"]

    def test_an_unknown_dimension_is_422(self, client, admin_auth_headers, board_data):
        resp = client.get(URL, params={"group_by": "group", "dimension": "color"}, headers=admin_auth_headers)

        assert resp.status_code == 422

    def test_the_product_and_publication_views_are_untouched(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers)

        assert body["group_by"] == "product" and body["dimension"] is None and body["levels"] is None
        assert _by_key(body)["11"]["products_count"] is None
        assert _by_key(body)["11"]["level"] is None


class TestGroupedPermissions:
    def test_without_ver_ganancia_the_groups_carry_no_margin(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_metricas.ver")
        db.add(
            ProductoERP(
                item_id=11, codigo="S", descripcion="Impresora", marca="Epson", categoria="C", subcategoria_id=1
            )
        )
        db.flush()
        _pub(db, 1, "MLA1", 11, 57997)
        _day(db, 11, "MLA1", date(2026, 9, 30), 2, "200", "30", "100")
        db.commit()

        row = _get(client, admin_auth_headers, **GROUP)["rows"][0]

        assert row["gross"] == 200
        assert row["total_gauss"] is None and row["markup_pct"] is None and row["series_markup_90d"] is None
        for sort in ("markup", "total_gauss", "markup_delta"):
            resp = client.get(URL, params={"sort": sort, **GROUP}, headers=admin_auth_headers)
            assert resp.status_code == 403, sort
        # Every level of the tree: the nodes and the products at its leaf.
        for path in (["EPSON"], ["EPSON", "C"], ["EPSON", "C", "1"]):
            below = client.get(NODES, params={"path": _path(*path), **GROUP}, headers=admin_auth_headers).json()["rows"]
            assert below, path
            assert below[0]["total_gauss"] is None and below[0]["markup_pct"] is None, path
            assert below[0]["series_markup_90d"] is None and below[0]["markup_delta_pp"] is None, path
        for sort in ("markup", "total_gauss", "markup_delta"):
            resp = client.get(NODES, params={"path": _path("EPSON"), "sort": sort, **GROUP}, headers=admin_auth_headers)
            assert resp.status_code == 403, sort

    def test_without_ver_everything_is_403(self, client, admin_auth_headers, db):
        assert client.get(URL, params=GROUP, headers=admin_auth_headers).status_code == 403
        assert client.get(NODES, params={"path": _path("X"), **GROUP}, headers=admin_auth_headers).status_code == 403


class TestGroupNodes:
    def test_a_node_opens_into_the_next_level(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, NODES, path=_path("EPSON"), **GROUP)

        assert body["level"] == "categoria" and body["total"] == 1
        assert [(r["key"], r["title"], r["level"], r["child_level"]) for r in body["rows"]] == [
            ("CAT", "Cat", "categoria", "subcategoria")
        ]
        assert body["rows"][0]["units"] == 6 and body["rows"][0]["products_count"] == 1
        assert len(body["rows"][0]["series_units_90d"]) == 90

    def test_the_last_level_opens_into_products(self, client, admin_auth_headers, board_data):
        subs = _get(client, admin_auth_headers, NODES, path=_path("EPSON", "CAT"), **GROUP)
        assert subs["level"] == "subcategoria" and [r["key"] for r in subs["rows"]] == ["1"]
        assert subs["rows"][0]["title"] == "Subcategoría #1"

        products = _get(client, admin_auth_headers, NODES, path=_path("EPSON", "CAT", "1"), **GROUP)

        assert products["level"] == "product"
        assert [r["product_item_id"] for r in products["rows"]] == [11]
        assert products["rows"][0]["units"] == 6 and products["rows"][0]["title"] == "Impresora Epson L3250"
        assert products["rows"][0]["level"] == "product" and products["rows"][0]["child_level"] is None

    def test_each_level_adds_up_to_the_node_above_it(self, client, admin_auth_headers, board_data):
        for dimension, depth in (("categoria", 2), ("marca", 3), ("tienda", 4), ("pm", 4), ("subcategoria", 1)):
            top = _get(client, admin_auth_headers, group_by="group", dimension=dimension)["rows"]

            def check(node, path):
                below = _get(
                    client, admin_auth_headers, NODES, path=_path(*path), group_by="group", dimension=dimension
                )["rows"]
                assert sum(r["units"] for r in below) == node["units"], (dimension, path)
                assert round(sum(r["gross"] for r in below), 2) == node["gross"], (dimension, path)
                if len(path) < depth:
                    for child in below:
                        check(child, [*path, child["key"]])

            for node in top:
                check(node, [node["key"]])

    def test_a_store_node_opens_down_to_the_products_with_only_its_sales(self, client, admin_auth_headers, board_data):
        params = {"group_by": "group", "dimension": "tienda"}
        marcas = _get(client, admin_auth_headers, NODES, path=_path("s:2645"), **params)
        assert [(r["key"], r["units"]) for r in marcas["rows"]] == [("LENOVO", 0)]

        products = _get(client, admin_auth_headers, NODES, path=_path("s:2645", "LENOVO", "CAT", "2"), **params)

        assert [(r["product_item_id"], r["units"]) for r in products["rows"]] == [(12, 0)]

    def test_nodes_come_in_pages_with_their_total_and_a_stable_order(self, client, admin_auth_headers, board_data):
        params = {"group_by": "group", "dimension": "tienda", "sort": "units_24h", "limit": 1}
        pages = [_get(client, admin_auth_headers, NODES, path=_path("s:57997"), offset=n, **params) for n in range(3)]

        assert [(p["total"], p["limit"], p["offset"]) for p in pages] == [(2, 1, 0), (2, 1, 1), (2, 1, 2)]
        keys = [r["key"] for p in pages for r in p["rows"]]
        assert len(keys) == len(set(keys)) == 2
        assert pages[2]["rows"] == []

    def test_the_sort_applies_inside_each_level(self, client, admin_auth_headers, board_data):
        asc = _get(
            client,
            admin_auth_headers,
            NODES,
            path=_path("s:57997"),
            sort="title",
            sort_dir="asc",
            group_by="group",
            dimension="tienda",
        )
        desc = _get(
            client,
            admin_auth_headers,
            NODES,
            path=_path("s:57997"),
            sort="title",
            sort_dir="desc",
            group_by="group",
            dimension="tienda",
        )

        assert [r["key"] for r in asc["rows"]] == list(reversed([r["key"] for r in desc["rows"]]))

    def test_searching_leaves_only_the_branches_with_matching_products(self, client, admin_auth_headers, board_data):
        top = _get(client, admin_auth_headers, q="notebook", group_by="group", dimension="categoria")
        subs = _get(
            client, admin_auth_headers, NODES, path=_path("CAT"), q="notebook", group_by="group", dimension="categoria"
        )
        products = _get(
            client,
            admin_auth_headers,
            NODES,
            path=_path("CAT", "2"),
            q="notebook",
            group_by="group",
            dimension="categoria",
        )

        assert [r["key"] for r in top["rows"]] == ["CAT"]
        assert [r["key"] for r in subs["rows"]] == ["2"]  # Lenovo's subcategoría only
        assert [r["product_item_id"] for r in products["rows"]] == [12]

    def test_a_path_is_required_and_must_be_a_json_list_of_the_right_size(self, client, admin_auth_headers, board_data):
        for bad in (None, "EPSON", "[]", '["A","B","C","D"]', "[1]", '[""]', "{}"):
            params = dict(GROUP, **({"path": bad} if bad is not None else {}))
            resp = client.get(NODES, params=params, headers=admin_auth_headers)
            assert resp.status_code == 422, bad

    def test_an_unknown_path_is_empty(self, client, admin_auth_headers, board_data):
        assert _get(client, admin_auth_headers, NODES, path=_path("NOPE"), **GROUP)["rows"] == []
        assert _get(client, admin_auth_headers, NODES, path=_path("EPSON", "NOPE", "9"), **GROUP)["rows"] == []

    def test_nodes_follow_the_boards_filters(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, NODES, path=_path("EPSON"), stores="144", **GROUP)

        assert body["rows"] == []


class TestGroupedExport:
    def test_csv_has_one_row_per_product_with_its_full_path(self, client, admin_auth_headers, board_data):
        resp = client.get(f"{URL}/export", params=GROUP, headers=admin_auth_headers)

        assert resp.status_code == 200 and "metricas-ml-por-marca-" in resp.headers["content-disposition"]
        header = resp.content.decode("utf-8-sig").splitlines()[0].split(";")
        assert header == [
            "Marca",
            "Categoría",
            "Subcategoría",
            "Producto",
            "SKU",
            "Publicaciones",
            "Unidades",
            "24h",
            "3d",
            "7d",
            "15d",
            "30d",
            "Facturado",
            "Total Gauss",
            "Markup %",
            "Markup anterior %",
            "Variación pp",
            "Última venta",
            "Ageing (días)",
            "Stock",
        ]
        rows = {row["Producto"]: row for row in _csv(resp)}
        assert set(rows) == {"Impresora Epson L3250", "Notebook Lenovo V15", "Taladro DeWalt", "Router TP-Link AX55"}
        epson = rows["Impresora Epson L3250"]
        assert (epson["Marca"], epson["Categoría"], epson["Subcategoría"]) == ("Epson", "Cat", "Subcategoría #1")
        assert epson["Unidades"] == "6" and epson["Markup %"] == "25,00" and epson["SKU"] == "SKU-11"

    def test_the_path_columns_follow_the_dimension(self, client, admin_auth_headers, board_data):
        headers = {}
        for dimension in ("categoria", "subcategoria", "pm", "tienda"):
            resp = client.get(
                f"{URL}/export", params={"group_by": "group", "dimension": dimension}, headers=admin_auth_headers
            )
            headers[dimension] = resp.content.decode("utf-8-sig").splitlines()[0].split(";")[:7]

        assert headers["categoria"] == [
            "Categoría",
            "Subcategoría",
            "Producto",
            "SKU",
            "Marca",
            "Publicaciones",
            "Unidades",
        ]
        assert headers["subcategoria"][:4] == ["Subcategoría · Categoría", "Producto", "SKU", "Marca"]
        assert headers["pm"][:5] == ["PM", "Marca", "Categoría", "Subcategoría", "Producto"]
        assert headers["tienda"][:5] == ["Tienda", "Marca", "Categoría", "Subcategoría", "Producto"]

    def test_a_product_in_two_stores_has_a_row_per_store(self, db, client, admin_auth_headers, board_data):
        _pub(db, 6, "MLA6", 11, 144)
        _day(db, 11, "MLA6", date(2026, 9, 30), 4, "400", "40", "200")
        db.commit()

        rows = _csv(
            client.get(f"{URL}/export", params={"group_by": "group", "dimension": "tienda"}, headers=admin_auth_headers)
        )

        epson = {row["Tienda"]: row["Unidades"] for row in rows if row["Producto"] == "Impresora Epson L3250"}
        assert epson == {"Tienda 57997": "6", "Tienda 144": "4"}

    def test_every_path_name_and_the_product_are_defused_against_formulas(
        self, db, client, admin_auth_headers, board_data
    ):
        db.add(ProductoERP(item_id=21, codigo="=1+1", descripcion="@x", marca='=HYPERLINK("x")', categoria="+cat"))
        db.flush()
        _pub(db, 21, "MLA21", 21, 57997)
        _day(db, 21, "MLA21", date(2026, 9, 30), 1, "100", "10", "50")
        db.commit()

        rows = _csv(client.get(f"{URL}/export", params=GROUP, headers=admin_auth_headers))

        evil = next(r for r in rows if r["Producto"] == "'@x")
        assert (evil["Marca"], evil["Categoría"], evil["SKU"]) == ('\'=HYPERLINK("x")', "'+cat", "'=1+1")

    def test_margin_columns_only_with_ver_ganancia(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_metricas.ver")
        db.commit()

        header = client.get(f"{URL}/export", params=GROUP, headers=admin_auth_headers).content.decode("utf-8-sig")

        assert "Total Gauss" not in header.splitlines()[0]

    def test_refuses_more_rows_than_the_cap(self, client, admin_auth_headers, board_data, monkeypatch):
        monkeypatch.setattr(ml_metricas, "EXPORT_MAX_ROWS", 3)

        resp = client.get(f"{URL}/export", params=GROUP, headers=admin_auth_headers)

        assert resp.status_code == 422

    def test_pages_by_key_like_the_product_export(self, client, admin_auth_headers, board_data, monkeypatch):
        monkeypatch.setattr(ml_metricas, "EXPORT_PAGE_SIZE", 2)

        resp = client.get(f"{URL}/export", params=GROUP, headers=admin_auth_headers)

        assert len(_csv(resp)) == 4


class TestGroupedStatementBudget:
    def test_a_fixed_number_of_statements_whatever_the_page_size(
        self, client, admin_auth_headers, board_data, query_counter
    ):
        counts = []
        for limit in (1, 50):
            with query_counter() as counter:
                _get(client, admin_auth_headers, limit=limit, **GROUP)
            counts.append(len(counter.statements))
        with query_counter() as counter:
            _get(client, admin_auth_headers)
        product_view = len(counter.statements)

        assert counts[0] == counts[1]
        # The group view pays for its own page, series and count -- never per row.
        assert counts[0] <= product_view + 3, (counts, product_view)

    def test_every_dimension_costs_the_same_statements(self, client, admin_auth_headers, board_data, query_counter):
        counts = {}
        for dimension in ("marca", "categoria", "subcategoria", "tienda", "pm"):
            with query_counter() as counter:
                _get(client, admin_auth_headers, group_by="group", dimension=dimension)
            counts[dimension] = len(counter.statements)

        assert len(set(counts.values())) == 1, counts

    def test_opening_a_node_at_any_depth_is_a_bounded_read(self, client, admin_auth_headers, board_data, query_counter):
        counts = []
        for path in (["EPSON"], ["EPSON", "C"], ["EPSON", "C", "1"]):
            with query_counter() as counter:
                _get(client, admin_auth_headers, NODES, path=_path(*path), **GROUP)
            counts.append(len(counter.statements))

        assert max(counts) <= 14, counts

    def test_the_grouped_export_is_a_fixed_number_of_statements_per_page(
        self, client, admin_auth_headers, board_data, query_counter, monkeypatch
    ):
        counts = []
        for page_size in (1, 100):
            monkeypatch.setattr(ml_metricas, "EXPORT_PAGE_SIZE", page_size)
            with query_counter() as counter:
                client.get(f"{URL}/export", params=GROUP, headers=admin_auth_headers)
            counts.append(len(counter.statements))

        # One statement set for the keys and one per page: 4 leaves, 4 pages vs 1.
        assert counts[0] - counts[1] <= 3 * 8, counts


class TestGroupedViewReview:
    def test_every_sort_of_the_board_works_on_the_grouped_view(self, client, admin_auth_headers, board_data):
        for sort in board.SORTS:
            for direction in ("asc", "desc"):
                resp = client.get(
                    URL, params={"sort": sort, "sort_dir": direction, **GROUP}, headers=admin_auth_headers
                )
                assert resp.status_code == 200, (sort, direction, resp.text)
                for path in (["EPSON"], ["EPSON", "CAT", "1"]):
                    below = client.get(
                        NODES,
                        params={"path": _path(*path), "sort": sort, "sort_dir": direction, **GROUP},
                        headers=admin_auth_headers,
                    )
                    assert below.status_code == 200, (sort, direction, path, below.text)

    def test_group_rows_carry_no_alerts(self, client, admin_auth_headers, board_data):
        rows = _get(client, admin_auth_headers, **GROUP)["rows"]

        assert rows and all(row["alerts"] == [] for row in rows)

    def test_tied_products_page_in_a_stable_order(self, client, admin_auth_headers, board_data):
        seen = []
        for offset in range(0, 4):
            body = _get(
                client,
                admin_auth_headers,
                NODES,
                path=_path("s:57997", "EPSON", "CAT", "1"),
                limit=1,
                offset=offset,
                sort="units_24h",
                group_by="group",
                dimension="tienda",
            )
            seen += [r["key"] for r in body["rows"]]

        assert len(seen) == len(set(seen)) == 1

    def test_the_csv_layouts_share_their_tail_columns(self, client, admin_auth_headers, board_data):
        product = client.get(f"{URL}/export", headers=admin_auth_headers).content.decode("utf-8-sig")
        grouped = client.get(f"{URL}/export", params=GROUP, headers=admin_auth_headers).content.decode("utf-8-sig")
        tail = [
            "Total Gauss",
            "Markup %",
            "Markup anterior %",
            "Variación pp",
            "Última venta",
            "Ageing (días)",
            "Stock",
        ]

        assert product.splitlines()[0].split(";")[-len(tail) :] == tail
        assert grouped.splitlines()[0].split(";")[-len(tail) :] == tail

    def test_every_level_has_a_csv_header(self):
        assert set(ml_metricas.LEVEL_HEADERS) == set(groups.LEVEL_KINDS)
