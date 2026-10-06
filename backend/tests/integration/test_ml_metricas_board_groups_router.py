"""ODD `metricas-ml-vista-agrupada` T3: `GET /api/ml-metricas/board?group_by=group`
(the "Agrupado" view), the endpoint that opens a group into its products, and
the grouped CSV. Same data, clock and permissions as the board's router tests
(`board_data`: products 11 Epson, 12 Lenovo, 13 DeWalt, 14 TP-Link; stores
57997, 2645, 144)."""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import csv
import io
from datetime import date

from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.producto import ProductoERP
from app.routers import ml_metricas
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

        assert body["group_by"] == "product" and body["dimension"] is None
        assert _by_key(body)["11"]["products_count"] is None


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
        products = client.get(
            f"{URL}/group-products", params={"group_key": "EPSON", **GROUP}, headers=admin_auth_headers
        ).json()["rows"]
        assert products[0]["total_gauss"] is None and products[0]["markup_pct"] is None

    def test_without_ver_everything_is_403(self, client, admin_auth_headers, db):
        assert client.get(URL, params=GROUP, headers=admin_auth_headers).status_code == 403
        assert (
            client.get(
                f"{URL}/group-products", params={"group_key": "X", **GROUP}, headers=admin_auth_headers
            ).status_code
            == 403
        )


class TestOpenAGroup:
    def test_a_group_opens_into_its_products(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, f"{URL}/group-products", group_key="EPSON", **GROUP)

        assert [r["product_item_id"] for r in body["rows"]] == [11]
        assert body["rows"][0]["units"] == 6 and body["rows"][0]["title"] == "Impresora Epson L3250"

    def test_a_store_group_opens_into_the_products_with_only_its_sales(self, client, admin_auth_headers, board_data):
        body = _get(
            client,
            admin_auth_headers,
            f"{URL}/group-products",
            group_key="s:2645",
            group_by="group",
            dimension="tienda",
        )

        assert [(r["product_item_id"], r["units"]) for r in body["rows"]] == [(12, 0)]

    def test_the_products_come_in_pages_with_their_total(self, client, admin_auth_headers, board_data):
        first = _get(
            client,
            admin_auth_headers,
            f"{URL}/group-products",
            group_key="s:57997",
            limit=1,
            sort="title",
            sort_dir="asc",
            group_by="group",
            dimension="tienda",
        )
        second = _get(
            client,
            admin_auth_headers,
            f"{URL}/group-products",
            group_key="s:57997",
            limit=1,
            offset=1,
            sort="title",
            sort_dir="asc",
            group_by="group",
            dimension="tienda",
        )

        assert (first["total"], first["limit"], first["offset"]) == (2, 1, 0)
        assert [r["product_item_id"] for r in first["rows"]] == [11]  # "Impresora..." before "Taladro..."
        assert [r["product_item_id"] for r in second["rows"]] == [13]

    def test_a_group_key_is_required_and_an_unknown_one_is_empty(self, client, admin_auth_headers, board_data):
        assert client.get(f"{URL}/group-products", params=GROUP, headers=admin_auth_headers).status_code == 422
        assert _get(client, admin_auth_headers, f"{URL}/group-products", group_key="NOPE", **GROUP)["rows"] == []

    def test_the_products_of_a_group_follow_the_boards_filters(self, client, admin_auth_headers, board_data):
        body = _get(client, admin_auth_headers, f"{URL}/group-products", group_key="EPSON", stores="144", **GROUP)

        assert body["rows"] == []


class TestGroupedExport:
    def test_csv_holds_every_group_with_a_fixed_column_list(self, client, admin_auth_headers, board_data):
        resp = client.get(f"{URL}/export", params=GROUP, headers=admin_auth_headers)

        assert resp.status_code == 200 and "metricas-ml-por-marca-" in resp.headers["content-disposition"]
        header = resp.content.decode("utf-8-sig").splitlines()[0].split(";")
        assert header == [
            "Marca",
            "Productos",
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
        rows = {row["Marca"]: row for row in _csv(resp)}
        assert set(rows) == {"Epson", "Lenovo", "DeWalt", "TP-Link"}
        assert rows["Epson"]["Unidades"] == "6" and rows["Epson"]["Markup %"] == "25,00"

    def test_the_group_name_is_defused_against_formulas(self, db, client, admin_auth_headers, board_data):
        db.add(ProductoERP(item_id=21, codigo="S21", descripcion="X", marca='=HYPERLINK("x")', categoria="C"))
        db.flush()
        _pub(db, 21, "MLA21", 21, 57997)
        _day(db, 21, "MLA21", date(2026, 9, 30), 1, "100", "10", "50")
        db.commit()

        names = [row["Marca"] for row in _csv(client.get(f"{URL}/export", params=GROUP, headers=admin_auth_headers))]

        assert '\'=HYPERLINK("x")' in names

    def test_margin_columns_only_with_ver_ganancia(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_metricas.ver")
        db.commit()

        header = client.get(f"{URL}/export", params=GROUP, headers=admin_auth_headers).content.decode("utf-8-sig")

        assert "Total Gauss" not in header.splitlines()[0]

    def test_refuses_more_groups_than_the_cap(self, client, admin_auth_headers, board_data, monkeypatch):
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

    def test_opening_a_group_is_a_bounded_read(self, client, admin_auth_headers, board_data, query_counter):
        with query_counter() as counter:
            _get(client, admin_auth_headers, f"{URL}/group-products", group_key="EPSON", **GROUP)

        assert len(counter.statements) <= 14, len(counter.statements)
