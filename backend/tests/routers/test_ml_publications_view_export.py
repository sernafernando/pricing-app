"""`GET /api/ml-publications/view/items/export` and `/products/export`: the current Publicaciones view as a CSV.

Same harness as the KPI strip's (`test_ml_publications_view_kpis.py`): permissions in the SQLite test database, the
store and the Board's tables in one throwaway Postgres schema that `get_background_db()` (each later page) also
reaches. What is pinned: the file follows the list (filters and order, across pages), the cap answers 422 before the
200, the permissions of the list apply (403s, the metrics and margin columns), BOM + `;`, free text defused, and a
page failing mid-stream ends the file with an error line.

The export closes the request session before streaming, which in this harness rolls back what the test flushed into
it (the grants): a test that also reads the list reads it BEFORE the export.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import csv
import io

import pytest

from app.services.ml_publications.view import export, listing, products as products_service
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import GANANCIA, VER, seed_rows
from tests.routers.test_ml_publications_view_ads import PERIOD, Exploding, FakeAds, provide  # noqa: F401
from tests.routers.test_ml_publications_view_kpis import METRICAS, _seller, pg, sell, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_markup import fill as markup_fill, pricing  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

ITEMS = "/api/ml-publications/view/items"
ITEMS_CSV = "/api/ml-publications/view/items/export"
PRODUCTS = "/api/ml-publications/view/products"
PRODUCTS_CSV = "/api/ml-publications/view/products/export"
MARGIN_ITEM_COLUMNS = {"Markup actual", "Markup real 30D", "Total Gauss 30D"}
METRIC_COLUMNS = {"Ventas 7D", "Ventas 30D", "Facturado 30D", "Última venta", "Ageing (días)"}


def read_csv(response) -> tuple[list[str], list[list[str]]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")  # Excel reads the accents as UTF-8
    rows = list(csv.reader(io.StringIO(text[1:]), delimiter=";"))
    return rows[0], rows[1:]


def column(header: list[str], rows: list[list[str]], name: str) -> list[str]:
    at = header.index(name)
    return [row[at] for row in rows]


def listed(client, headers, url, key, **params) -> list:
    response = client.get(url, headers=headers, params={"limit": 100, **params})
    assert response.status_code == 200, response.text
    body = response.json()
    return [row[key] for row in body["items" if "items" in body else "rows"]]


@pytest.fixture()
def small_pages(monkeypatch):
    monkeypatch.setattr(export, "EXPORT_PAGE_SIZE", 2)


def fill(conn) -> None:
    seed.add_product(conn, 77, "R77", "Router AX", marca="TP-Link", stock=4)
    seed.add_product(conn, 78, "R78", "Antena", marca="Ubiquiti")
    seed.add_item(conn, "MLA1", title="Delta", status="active", price=1000)
    seed.add_item(conn, "MLA2", title='=HYPERLINK("http://x")', status="active")  # no link: "Sin producto"
    seed.add_item(conn, "MLA3", title="Alfa", status="paused")
    seed.add_item(conn, "MLA4", title="Charlie", status="active")
    seed.add_item(conn, "MLA5", title="Bravo", status="active")
    seed.add_link(conn, "MLA1", 77)
    seed.add_link(conn, "MLA3", 77)
    seed.add_link(conn, "MLA4", 78)


@pytest.fixture()
def sold(pg):
    seed_rows(pg, fill)
    sell(pg, (1, [("MLA1", None, 2)]), (2, [("MLA4", None, 1)]), accredited=seed.real_hours_ago(1))
    return pg


class TestItemsPermission:
    def test_a_user_without_ml_ops_ver_gets_403(self, client, pg, db, rol_ventas, auth_headers) -> None:
        grant(db, rol_ventas, METRICAS, GANANCIA)
        response = client.get(ITEMS_CSV, headers=auth_headers)
        assert response.status_code == 403 and VER in response.json()["error"]["message"]

    @pytest.mark.parametrize(
        "params", [{"orden": "markup"}, {"markup_neg": "true"}, {"markup_min": "0"}, {"restar_publicidad": "true"}]
    )
    def test_markup_parameters_need_ver_ganancia(self, client, pg, db, rol_admin, admin_auth_headers, params) -> None:
        grant(db, rol_admin, VER, METRICAS)
        response = client.get(ITEMS_CSV, headers=admin_auth_headers, params=params)
        assert response.status_code == 403 and GANANCIA in response.json()["error"]["message"]

    def test_a_metric_sort_needs_ml_metricas_ver(self, client, pg, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, GANANCIA)
        response = client.get(ITEMS_CSV, headers=admin_auth_headers, params={"orden": "facturado_30d"})
        assert response.status_code == 403 and METRICAS in response.json()["error"]["message"]

    def test_a_bad_filter_is_a_422_before_any_byte(self, client, pg, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER)
        response = client.get(ITEMS_CSV, headers=admin_auth_headers, params={"estado": "bogus"})
        assert response.status_code == 422 and response.json()["error"]["field"] == "estado"


class TestItems:
    def test_the_file_is_semicolons_with_a_bom_and_names_itself(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER)
        response = client.get(ITEMS_CSV, headers=admin_auth_headers, params={"orden": "titulo"})
        header, rows = read_csv(response)
        assert header[:3] == ["Publicación", "Título", "Estado"]
        assert 'filename="publicaciones-ml-' in response.headers["content-disposition"]
        assert len(rows) == 5 and all(len(row) == len(header) for row in rows)
        by_id = {row[0]: dict(zip(header, row)) for row in rows}
        assert by_id["MLA1"]["Código"] == "R77" and by_id["MLA1"]["Producto"] == "Router AX"
        assert by_id["MLA1"]["Precio"] == "1000,00"

    def test_a_cell_that_would_start_a_formula_is_defused(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER)
        header, rows = read_csv(client.get(ITEMS_CSV, headers=admin_auth_headers))
        titles = dict(zip(column(header, rows, "Publicación"), column(header, rows, "Título")))
        assert titles["MLA2"] == '\'=HYPERLINK("http://x")'

    def test_the_filters_and_the_order_follow_the_list_across_pages(
        self, client, sold, db, rol_admin, admin_auth_headers, small_pages
    ):
        grant(db, rol_admin, VER)
        params = {"estado": "active", "orden": "titulo", "dir": "desc"}
        expected = listed(client, admin_auth_headers, ITEMS, "item_id", **params)
        header, rows = read_csv(client.get(ITEMS_CSV, headers=admin_auth_headers, params=params))
        # the paused one is filtered out; 2 pages of 2. The exact title order depends on the server collation
        # (the '=HYPERLINK' title sorts apart under C vs ICU), so pin the set and that the export follows the list.
        assert sorted(expected) == ["MLA1", "MLA2", "MLA4", "MLA5"]
        assert column(header, rows, "Publicación") == expected

    def test_a_metric_sort_follows_the_list(self, client, sold, db, rol_admin, admin_auth_headers, small_pages):
        grant(db, rol_admin, VER, METRICAS)
        expected = listed(client, admin_auth_headers, ITEMS, "item_id", orden="unidades_30d")
        header, rows = read_csv(client.get(ITEMS_CSV, headers=admin_auth_headers, params={"orden": "unidades_30d"}))
        assert expected[:2] == ["MLA1", "MLA4"]
        assert column(header, rows, "Publicación") == expected

    def test_over_the_cap_is_a_422_asking_to_narrow_the_filters(
        self, client, sold, db, rol_admin, admin_auth_headers, monkeypatch
    ):
        grant(db, rol_admin, VER)
        monkeypatch.setattr(export, "EXPORT_MAX_ROWS", 4)
        response = client.get(ITEMS_CSV, headers=admin_auth_headers)
        assert response.status_code == 422
        assert "filtros" in response.json()["error"]["message"]

    def test_exactly_the_cap_is_exported(self, client, sold, db, rol_admin, admin_auth_headers, monkeypatch):
        grant(db, rol_admin, VER)
        monkeypatch.setattr(export, "EXPORT_MAX_ROWS", 5)
        assert len(read_csv(client.get(ITEMS_CSV, headers=admin_auth_headers))[1]) == 5

    def test_without_metricas_or_margin_there_are_no_such_columns(
        self, client, sold, db, rol_admin, admin_auth_headers
    ):
        grant(db, rol_admin, VER)
        header, _ = read_csv(client.get(ITEMS_CSV, headers=admin_auth_headers))
        assert not (METRIC_COLUMNS | MARGIN_ITEM_COLUMNS) & set(header)

    def test_metricas_adds_the_sales_columns_but_not_the_margin(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS)
        header, rows = read_csv(client.get(ITEMS_CSV, headers=admin_auth_headers))
        assert METRIC_COLUMNS <= set(header) and not MARGIN_ITEM_COLUMNS & set(header)
        units = dict(zip(column(header, rows, "Publicación"), column(header, rows, "Ventas 30D")))
        assert (units["MLA1"], units["MLA4"], units["MLA3"]) == ("2", "1", "")

    def test_ver_ganancia_adds_the_margin_columns(self, client, sold, db, rol_admin, admin_auth_headers, pricing):
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        header, rows = read_csv(client.get(ITEMS_CSV, headers=admin_auth_headers))
        assert MARGIN_ITEM_COLUMNS <= set(header)
        real = dict(zip(column(header, rows, "Publicación"), column(header, rows, "Markup real 30D")))
        assert real["MLA1"] == "100,00"  # every seeded order: Total Gauss 1 over cost 1

    def test_a_page_failing_mid_stream_ends_the_file_with_an_error_line(
        self, client, sold, db, rol_admin, admin_auth_headers, small_pages, monkeypatch
    ):
        grant(db, rol_admin, VER)
        real, calls = listing.items_for_keys, []

        def flaky(*args, **kwargs):
            calls.append(1)
            if len(calls) > 1:
                raise RuntimeError("boom")
            return real(*args, **kwargs)

        monkeypatch.setattr(listing, "items_for_keys", flaky)
        response = client.get(ITEMS_CSV, headers=admin_auth_headers)
        text = response.content.decode("utf-8")
        assert response.status_code == 200
        assert text.rstrip("\n").splitlines()[-1].startswith("# ERROR: exportación incompleta — 2 de 5 filas")


class TestItemsMarkup:
    """The markup sort and filter run in Python over the whole set (`listing._list_by_markup`): the keys honor them."""

    @pytest.fixture()
    def priced(self, pg, db, rol_admin, admin_auth_headers, pricing, small_pages):
        seed_rows(pg, markup_fill)
        grant(db, rol_admin, VER, GANANCIA)
        return admin_auth_headers

    @pytest.mark.parametrize(
        "params",
        [
            {"orden": "markup"},
            {"orden": "markup", "dir": "desc"},
            {"markup_neg": "true", "orden": "titulo"},
            {"markup_min": "0", "orden": "precio"},
        ],
    )
    def test_the_markup_order_and_filters_follow_the_list(self, client, priced, params) -> None:
        expected = listed(client, priced, ITEMS, "item_id", **params)
        header, rows = read_csv(client.get(ITEMS_CSV, headers=priced, params=params))
        assert expected and column(header, rows, "Publicación") == expected
        assert "Markup actual" in header

    def test_the_markup_column_is_the_worst_variation(self, client, priced) -> None:
        expected = client.get(ITEMS, headers=priced, params={"orden": "markup"}).json()["items"]
        header, rows = read_csv(client.get(ITEMS_CSV, headers=priced, params={"orden": "markup"}))
        worst = [row["markup"]["worst"] for row in expected]
        assert column(header, rows, "Markup actual") == [
            "" if value is None else f"{value:.2f}".replace(".", ",") for value in worst
        ]


class TestItemsAds:
    """`restar_publicidad`: when the Ads cost could not be applied (provider down or unavailable), the list says so
    in its `ads` block; the file says so in a trailing line, as the mid-stream error does."""

    NOTE = "# AVISO: el markup no descuenta la publicidad"

    @pytest.fixture()
    def priced(self, pg, db, rol_admin, admin_auth_headers, pricing, small_pages):
        seed_rows(pg, markup_fill)
        grant(db, rol_admin, VER, GANANCIA)
        return admin_auth_headers

    @pytest.mark.parametrize("where", ["amounts", "availability"])
    def test_a_failing_provider_is_stated_in_the_file(self, client, priced, provide, where) -> None:
        provide(Exploding(where))
        params = {"restar_publicidad": "true", **PERIOD}
        assert client.get(ITEMS, headers=priced, params=params).json()["ads"]["reason"] == "provider_error"
        response = client.get(ITEMS_CSV, headers=priced, params=params)
        assert response.status_code == 200
        lines = response.content.decode("utf-8").rstrip("\n").splitlines()
        assert lines[-1].startswith(self.NOTE)
        assert len(lines) == 1 + 6 + 1  # header, every row, the note: nothing was dropped

    class FlakyAds:
        """Fails (or answers) the first `amounts` read and does the opposite afterwards; counts the reads."""

        def __init__(self, fail_first: bool) -> None:
            self.fail_first = fail_first
            self.reads = 0

        def availability(self):
            return FakeAds({}).availability()

        def amounts(self, mla_ids, date_from, date_to):
            self.reads += 1
            if (self.reads == 1) == self.fail_first:
                raise RuntimeError("billing is down")
            return {"MLA1": 100.0}  # no units sold: MLA1 has no markup net of Ads, so the order moves

    @pytest.mark.parametrize("params", [{"orden": "markup"}, {"markup_min": "0", "orden": "titulo"}])
    def test_ads_are_read_once_and_a_failure_orders_and_prices_by_the_plain_markup(
        self, client, priced, provide, params
    ) -> None:
        plain = listed(client, priced, ITEMS, "item_id", **params)
        flaky = self.FlakyAds(fail_first=True)
        provide(flaky)
        response = client.get(ITEMS_CSV, headers=priced, params={"restar_publicidad": "true", **PERIOD, **params})
        lines = response.content.decode("utf-8").rstrip("\n").splitlines()
        assert flaky.reads == 1
        assert lines[-1].startswith(self.NOTE)
        header, rows = read_csv(response)
        assert column(header, rows[:-1], "Publicación") == plain

    @pytest.mark.parametrize("params", [{"orden": "markup"}, {"markup_min": "0", "orden": "titulo"}])
    def test_ads_read_once_order_and_price_the_file_together(self, client, priced, provide, params) -> None:
        params = {"restar_publicidad": "true", **PERIOD, **params}
        provide(FakeAds({"MLA1": 100.0}))
        expected = listed(client, priced, ITEMS, "item_id", **params)
        flaky = self.FlakyAds(fail_first=False)  # a second read would fail: there must be none
        provide(flaky)
        header, rows = read_csv(client.get(ITEMS_CSV, headers=priced, params=params))
        assert flaky.reads == 1
        assert not any(row[0].startswith("#") for row in rows)
        assert column(header, rows, "Publicación") == expected

    def test_applied_ads_add_no_note(self, client, priced, provide) -> None:
        provide(FakeAds({"MLA1": 100.0}))
        response = client.get(ITEMS_CSV, headers=priced, params={"restar_publicidad": "true", **PERIOD})
        header, rows = read_csv(response)
        assert len(rows) == 6 and not any(row[0].startswith("#") for row in rows)

    def test_without_restar_publicidad_there_is_no_note(self, client, priced, provide) -> None:
        provide(Exploding("amounts"))
        _, rows = read_csv(client.get(ITEMS_CSV, headers=priced))
        assert len(rows) == 6 and not any(row[0].startswith("#") for row in rows)


class TestProducts:
    def test_a_user_without_ml_ops_ver_gets_403(self, client, pg, db, rol_ventas, auth_headers) -> None:
        grant(db, rol_ventas, METRICAS, GANANCIA)
        assert client.get(PRODUCTS_CSV, headers=auth_headers).status_code == 403

    def test_a_metric_sort_needs_ml_metricas_ver(self, client, pg, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, GANANCIA)
        response = client.get(PRODUCTS_CSV, headers=admin_auth_headers, params={"orden": "facturado_30d"})
        assert response.status_code == 403 and METRICAS in response.json()["error"]["message"]

    def test_a_margin_sort_needs_ver_ganancia(self, client, pg, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, METRICAS)
        response = client.get(PRODUCTS_CSV, headers=admin_auth_headers, params={"orden": "markup_30d"})
        assert response.status_code == 403 and GANANCIA in response.json()["error"]["message"]

    def test_the_rows_and_columns_without_metricas(self, client, sold, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER)
        header, rows = read_csv(client.get(PRODUCTS_CSV, headers=admin_auth_headers))
        assert header[:4] == ["Código", "Producto", "Marca", "Publicaciones"]
        assert not (METRIC_COLUMNS | MARGIN_ITEM_COLUMNS) & set(header)
        # the default sort without ml_metricas.ver is the name, "Sin producto" last
        assert [row[:4] for row in rows] == [
            ["R78", "Antena", "Ubiquiti", "1"],
            ["R77", "Router AX", "TP-Link", "2"],
            ["", "Sin producto", "", "2"],
        ]

    def test_metricas_and_margin_columns_are_gated(self, client, sold, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, METRICAS)
        header, rows = read_csv(client.get(PRODUCTS_CSV, headers=admin_auth_headers))
        assert METRIC_COLUMNS <= set(header) and not {"Markup real 30D", "Total Gauss 30D"} & set(header)
        assert column(header, rows, "Ventas 30D")[0] == "2"  # the default sort: facturado_30d, Router AX first

    def test_ver_ganancia_adds_the_margin(self, client, sold, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        header, rows = read_csv(client.get(PRODUCTS_CSV, headers=admin_auth_headers))
        assert {"Markup real 30D", "Total Gauss 30D"} <= set(header)
        assert column(header, rows, "Markup real 30D")[0] == "100,00"

    @pytest.mark.parametrize(
        "params",
        [{}, {"orden": "titulo", "dir": "desc"}, {"orden": "unidades_30d", "dir": "asc"}, {"estado": "active"}],
    )
    def test_the_order_and_filters_follow_the_list_across_pages(
        self, client, sold, db, rol_admin, admin_auth_headers, monkeypatch, params
    ) -> None:
        grant(db, rol_admin, VER, METRICAS)
        monkeypatch.setattr(export, "EXPORT_PAGE_SIZE", 1)
        expected = listed(client, admin_auth_headers, PRODUCTS, "descripcion", **params)
        names = [name or "Sin producto" for name in expected]
        header, rows = read_csv(client.get(PRODUCTS_CSV, headers=admin_auth_headers, params=params))
        assert len(names) >= 2 and column(header, rows, "Producto") == names

    def test_over_the_cap_is_a_422(self, client, sold, db, rol_admin, admin_auth_headers, monkeypatch) -> None:
        grant(db, rol_admin, VER)
        monkeypatch.setattr(export, "EXPORT_MAX_ROWS", 2)
        response = client.get(PRODUCTS_CSV, headers=admin_auth_headers)
        assert response.status_code == 422 and "filtros" in response.json()["error"]["message"]

    def test_a_page_failing_mid_stream_ends_the_file_with_an_error_line(
        self, client, sold, db, rol_admin, admin_auth_headers, monkeypatch
    ) -> None:
        grant(db, rol_admin, VER)
        monkeypatch.setattr(export, "EXPORT_PAGE_SIZE", 1)
        real, calls = products_service.products_for_keys, []

        def flaky(*args, **kwargs):
            calls.append(1)
            if len(calls) > 2:
                raise RuntimeError("boom")
            return real(*args, **kwargs)

        monkeypatch.setattr(products_service, "products_for_keys", flaky)
        text = client.get(PRODUCTS_CSV, headers=admin_auth_headers).content.decode("utf-8")
        lines = text.rstrip("\n").splitlines()
        assert len(lines) == 4  # header, two rows, the error
        assert lines[-1].startswith("# ERROR: exportación incompleta — 2 de 3 filas")
