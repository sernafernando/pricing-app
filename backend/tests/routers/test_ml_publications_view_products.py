"""`GET /api/ml-publications/view/products`: the Producto view (permissions, shape, sorts, paging).

Same harness as the KPI strip's (`test_ml_publications_view_kpis.py`): the store and the Board's tables in one
throwaway Postgres schema. The arithmetic is pinned in `view/test_products_postgres.py`; this file pins the HTTP
surface: the rows need `ml_ops.ver`, their Métricas figures `ml_metricas.ver`, the margin `ml_metricas.ver_ganancia`.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest
from sqlalchemy import delete, func

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.services.ml_publications.view import listing, products as products_service, status_block
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import GANANCIA, VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import METRICAS, _seller, pg, sell, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

URL = "/api/ml-publications/view/products"
MARGIN = {"total_gauss_30d", "markup_30d", "markup_delta_pp", "series_markup_90d"}


def fill(conn) -> None:
    seed.add_product(conn, 77, "R77", "Router AX", marca="TP-Link", stock=4)
    seed.add_product(conn, 78, "R78", "Antena", marca="Ubiquiti")
    seed.add_item(conn, "MLA1", status="active")
    seed.add_item(conn, "MLA2", status="active")  # no link: "Sin producto"
    seed.add_item(conn, "MLA3", status="paused")
    seed.add_item(conn, "MLA4", status="active")  # linked, never sold: a row with no figures
    seed.add_link(conn, "MLA1", 77)
    seed.add_link(conn, "MLA3", 77)
    seed.add_link(conn, "MLA4", 78)


@pytest.fixture()
def sold(pg):
    seed_rows(pg, fill)
    sell(
        pg,
        (1, [("MLA1", None, 2)]),
        (2, [("MLA2", None, 4)]),
        (3, [("MLA3", None, 1)]),
        accredited=seed.real_hours_ago(1),
    )
    with pg.begin() as conn:  # every sale's cost names 77; MLA2 is still "Sin producto": the link decides
        conn.execute(delete(MlOrderItemCosto).where(MlOrderItemCosto.order_id == 2))
    return pg


def get(client, headers, **params):
    return client.get(URL, headers=headers, params=params)


def body(client, headers, **params) -> dict:
    response = get(client, headers, **params)
    assert response.status_code == 200, response.text
    return response.json()


def by_key(rows: list) -> dict:
    return {row["key"]: row for row in rows}


class TestPermission:
    def test_authentication_is_required(self, client, pg) -> None:
        assert client.get(URL).status_code in (401, 403)

    def test_a_user_without_ml_ops_ver_gets_403(self, client, pg, db, rol_ventas, auth_headers) -> None:
        grant(db, rol_ventas, METRICAS, GANANCIA)
        response = get(client, auth_headers)
        assert response.status_code == 403 and VER in response.json()["error"]["message"]

    def test_a_metric_sort_needs_ml_metricas_ver(self, client, sold, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, GANANCIA)
        response = get(client, admin_auth_headers, orden="facturado_30d")
        assert response.status_code == 403 and METRICAS in response.json()["error"]["message"]

    def test_a_margin_sort_needs_ver_ganancia(self, client, sold, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, METRICAS)
        response = get(client, admin_auth_headers, orden="markup_30d")
        assert response.status_code == 403 and GANANCIA in response.json()["error"]["message"]

    def test_without_ml_metricas_ver_the_rows_come_by_title_and_without_figures(
        self, client, sold, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER)
        got = body(client, admin_auth_headers)
        assert [row["key"] for row in got["rows"]] == ["78", "77", "0"]  # by name, "Sin producto" last
        assert all("metrics" not in row for row in got["rows"])


class TestRows:
    def test_a_product_row_carries_what_the_screen_draws(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS)
        row = by_key(body(client, admin_auth_headers, estado="active")["rows"])["77"]
        assert {k: row[k] for k in ("product_item_id", "codigo", "descripcion", "marca", "publications_count")} == {
            "product_item_id": 77,
            "codigo": "R77",
            "descripcion": "Router AX",
            "marca": "TP-Link",
            "publications_count": 1,  # MLA3 is paused: out of the set
        }
        assert row["stock"] == 4
        assert row["params"] == {"producto": "77"}
        assert "thumbnail" not in row

    def test_the_sin_producto_bucket_opens_the_publications_without_product(
        self, client, sold, db, rol_admin, admin_auth_headers
    ):
        grant(db, rol_admin, VER, METRICAS)
        row = by_key(body(client, admin_auth_headers, estado="active")["rows"])["0"]
        assert (row["product_item_id"], row["descripcion"]) == (None, "Sin producto")
        assert row["params"] == {"sin_producto": "true"}

    def test_figures_with_ml_metricas_ver_and_no_margin_without_ver_ganancia(
        self, client, sold, db, rol_admin, admin_auth_headers
    ):
        grant(db, rol_admin, VER, METRICAS)
        metrics = by_key(body(client, admin_auth_headers, estado="active")["rows"])["77"]["metrics"]
        assert (metrics["units_7d"], metrics["units_30d"], metrics["gross_30d"]) == (2, 2, 20.0)
        assert len(metrics["series_units_90d"]) == 90
        assert MARGIN.isdisjoint(metrics)

    def test_a_product_none_of_whose_publications_sold_has_null_metrics(
        self, client, sold, db, rol_admin, admin_auth_headers
    ):
        grant(db, rol_admin, VER, METRICAS)
        row = by_key(body(client, admin_auth_headers, estado="active")["rows"])["78"]
        assert (row["publications_count"], row["metrics"]) == (1, None)

    def test_the_margin_comes_with_ver_ganancia(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        got = body(client, admin_auth_headers, estado="active")
        assert got["can_see_margin"] is True
        metrics = by_key(got["rows"])["77"]["metrics"]
        assert MARGIN <= set(metrics) and metrics["markup_30d"] == 100.0  # every seeded order: TG 1 over cost 1


class TestPaging:
    def test_sorted_by_a_figure_paged_and_counted(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS)
        first = body(client, admin_auth_headers, orden="unidades_30d", dir="desc", limit=1)
        second = body(client, admin_auth_headers, orden="unidades_30d", dir="desc", limit=1, offset=1)
        assert [r["key"] for r in first["rows"] + second["rows"]] == ["0", "77"]  # 4 units vs 2 + 1
        assert (first["total"], first["mla_count"], first["limit"], first["offset"]) == (3, 4, 1, 0)

    def test_the_default_is_by_gross_descending(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS)
        assert [r["key"] for r in body(client, admin_auth_headers)["rows"]] == ["0", "77", "78"]  # no sales last

    def test_an_unknown_sort_is_a_422_naming_it(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS)
        response = get(client, admin_auth_headers, orden="precio")
        assert response.status_code == 422 and response.json()["error"]["field"] == "orden"

    def test_the_filters_are_the_lists(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS)
        response = get(client, admin_auth_headers, estado="bogus")
        assert response.status_code == 422 and response.json()["error"]["field"] == "estado"


class TestInvalidParams:
    @pytest.mark.parametrize(
        "params, field",
        [
            ({"dir": "sideways"}, "dir"),
            ({"evento": "price_changed"}, "evento"),  # the events flag is off
        ],
    )
    def test_a_bad_value_is_422_naming_the_param(self, client, sold, db, rol_admin, admin_auth_headers, params, field):
        grant(db, rol_admin, VER, METRICAS)
        response = get(client, admin_auth_headers, **params)
        assert response.status_code == 422 and response.json()["error"]["field"] == field


class TestSlowQuery:
    def test_a_statement_timeout_is_a_controlled_503_and_the_connection_goes_back(
        self, client, sold, db, rol_admin, admin_auth_headers, monkeypatch
    ) -> None:
        grant(db, rol_admin, VER, METRICAS)
        real = products_service.build_base_select

        def slow(f, *columns, **kwargs):  # the set is one column, so the delay goes in the WHERE
            return real(f, *columns, **kwargs).where(func.pg_sleep(1).is_not(None))

        monkeypatch.setattr(listing, "STATEMENT_TIMEOUT", "50ms")
        monkeypatch.setattr(products_service, "build_base_select", slow)
        response = get(client, admin_auth_headers)
        assert response.status_code == 503 and response.json()["error"]["code"] == "consulta_lenta"
        assert sold.pool.checkedout() == 0
        monkeypatch.setattr(listing, "STATEMENT_TIMEOUT", "8s")
        monkeypatch.setattr(products_service, "build_base_select", real)
        status_block.REPORT.reset()
        assert get(client, admin_auth_headers).status_code == 200


@pytest.fixture()
def unlinked(sold):
    with sold.begin() as conn:
        seed.add_product(conn, 79, "S79", "Switch", marca="Kabel", stock=2)  # no publication is linked to it
    return sold


class TestSinMla:
    """`con_mla=false`: Productos' "Sin MLA", the products no publication is linked to (service tests:
    `tests/services/ml_publications/view/test_products_sin_mla_postgres.py`)."""

    def test_lists_the_products_without_mla_and_counts_them(
        self, client, unlinked, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER)
        got = body(client, admin_auth_headers, con_mla="false")
        assert [row["key"] for row in got["rows"]] == ["79"]
        assert (got["total"], got["mla_count"], got["sin_mla_count"]) == (1, 0, 1)
        assert got["rows"][0]["publications_count"] == 0

    def test_every_page_says_how_many_products_have_no_mla(
        self, client, unlinked, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER)
        assert body(client, admin_auth_headers)["sin_mla_count"] == 1
        assert body(client, admin_auth_headers, marcas="TP-Link")["sin_mla_count"] == 0

    def test_with_a_publication_filter_the_count_is_absent(
        self, client, unlinked, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER)
        assert "sin_mla_count" not in body(client, admin_auth_headers, estado="active")

    def test_a_publication_filter_is_a_422_naming_it(self, client, unlinked, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER)
        for url in (URL, URL + "/export", "/api/ml-publications/view/product-ids"):
            response = client.get(url, headers=admin_auth_headers, params={"con_mla": "false", "estado": "active"})
            assert response.status_code == 422, (url, response.text)
            assert "estado" in response.text

    def test_a_figure_sort_answers_the_name_sort_it_falls_back_to(
        self, client, unlinked, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER, METRICAS)
        got = body(client, admin_auth_headers, con_mla="false", orden="facturado_30d", dir="desc")
        assert (got["orden"], got["dir"]) == ("titulo", "asc")  # what the rows are sorted by, not what was asked

    def test_the_publication_reads_select_nothing(self, client, unlinked, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, "ml_publicaciones.pausar")
        items = client.get("/api/ml-publications/view/items", headers=admin_auth_headers, params={"con_mla": "false"})
        assert items.status_code == 200, items.text
        assert (items.json()["items"], items.json()["total"]) == ([], 0)
        status_ids = client.get(
            "/api/ml-publications/view/status-item-ids",
            headers=admin_auth_headers,
            params={"con_mla": "false", "target": "paused"},
        )
        assert status_ids.status_code == 200, status_ids.text
        assert status_ids.json()["item_ids"] == []  # a status action never reaches a publication from here

    def test_con_mla_true_is_the_usual_view(self, client, unlinked, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER)
        usual = body(client, admin_auth_headers)
        assert body(client, admin_auth_headers, con_mla="true")["rows"] == usual["rows"]

    def test_the_bulk_ids_and_the_export_are_the_same_products(
        self, client, unlinked, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER)
        ids = client.get(
            "/api/ml-publications/view/product-ids", headers=admin_auth_headers, params={"con_mla": "false"}
        )
        assert ids.status_code == 200, ids.text
        assert (ids.json()["item_ids"], ids.json()["count"]) == ([79], 1)
        csv = client.get(URL + "/export", headers=admin_auth_headers, params={"con_mla": "false"})
        assert csv.status_code == 200, csv.text
        lines = [line for line in csv.text.splitlines() if line.strip()]
        assert len(lines) == 2 and "S79" in lines[1]
