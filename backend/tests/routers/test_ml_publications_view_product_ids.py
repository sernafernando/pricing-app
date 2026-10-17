"""`GET /api/ml-publications/view/product-ids`: the products a Publicaciones ML filter selects, for a bulk action.

A bulk pricing action acts on PRODUCTS: the linked products of the publications the filter matches. This endpoint
names them, with the same filters (`filter_query`) and the same base select as `/products`, so the count the button
shows is the product rows the Producto view lists. Publications with no linked product are left out and counted
apart (`sin_producto`). Over the cap it refuses (422), never truncates: a bulk write over a partial set is the bug
this endpoint exists to prevent.

Same harness as `/products` (`test_ml_publications_view_products.py`): the store in a throwaway Postgres schema.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest

from app.services.ml_publications.view import products as products_service
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER
from tests.routers.test_ml_publications_view_kpis import METRICAS, _seller, pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_presence import TOGGLES, mixed, reader  # noqa: F401
from tests.routers.test_ml_publications_view_products import sold  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

pytestmark = pytest.mark.postgres

URL = "/api/ml-publications/view/product-ids"
PRODUCTS_URL = "/api/ml-publications/view/products"


def get(client, headers, **params):
    return client.get(URL, headers=headers, params=params)


def body(client, headers, **params) -> dict:
    response = get(client, headers, **params)
    assert response.status_code == 200, response.text
    return response.json()


class TestPermission:
    def test_authentication_is_required(self, client, pg) -> None:
        assert client.get(URL).status_code in (401, 403)

    def test_a_user_without_ml_ops_ver_gets_403(self, client, pg, db, rol_ventas, auth_headers) -> None:
        grant(db, rol_ventas, METRICAS)
        response = get(client, auth_headers)
        assert response.status_code == 403 and VER in response.json()["error"]["message"]


class TestProducts:
    def test_the_linked_products_of_the_matching_publications(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER)
        # MLA1 -> 77, MLA2 no product, MLA3 (paused) -> 77, MLA4 -> 78
        assert body(client, admin_auth_headers) == {
            "item_ids": [77, 78],
            "count": 2,
            "sin_producto": 1,
            "fuera_de_catalogo": 0,
        }

    def test_the_filters_narrow_the_set(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER)
        got = body(client, admin_auth_headers, estado="paused")
        assert got == {"item_ids": [77], "count": 1, "sin_producto": 0, "fuera_de_catalogo": 0}

    def test_a_product_counts_once_however_many_publications_match(
        self, client, sold, db, rol_admin, admin_auth_headers
    ):
        grant(db, rol_admin, VER)
        got = body(client, admin_auth_headers, estado="active,paused", marcas="TP-Link")
        assert got == {"item_ids": [77], "count": 1, "sin_producto": 0, "fuera_de_catalogo": 0}

    def test_an_empty_selection_is_empty(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER)
        assert body(client, admin_auth_headers, q="nothing-matches-this") == {
            "item_ids": [],
            "count": 0,
            "sin_producto": 0,
            "fuera_de_catalogo": 0,
        }

    @pytest.mark.parametrize(
        "params",
        [{}, {"estado": "active"}, {"estado": "paused"}, {"marcas": "Ubiquiti"}],
    )
    def test_the_count_is_the_product_rows_of_the_producto_view(
        self, client, sold, db, rol_admin, admin_auth_headers, params
    ):
        """The contract the button relies on: the products it acts on are the Producto view's product rows."""
        grant(db, rol_admin, VER)
        assert_matches_the_producto_view(client, admin_auth_headers, params)


def assert_matches_the_producto_view(client, headers, params: dict) -> None:
    # what the Producto view asks (`buildKpiParams`): the offer of the product, as its rows ask it
    same = {**params, "oferta_por_producto": "true"} if "con_oferta" in params else params
    response = client.get(PRODUCTS_URL, headers=headers, params={**params, "limit": 100})
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    linked = sorted(row["product_item_id"] for row in rows if row["product_item_id"] is not None)
    got = body(client, headers, **same)
    assert (got["item_ids"], got["count"]) == (linked, len(linked))


class TestPresenceToggles:
    """S5's toggles, over the presence harness: 77 has MLA1 (on offer) and MLA4 (not); 78 has MLA2; MLA3 has none."""

    @pytest.mark.parametrize("toggle", TOGGLES, ids=lambda t: "=".join(*t.items()))
    def test_every_toggle_agrees_with_the_producto_view(self, client, mixed, toggle):
        assert_matches_the_producto_view(client, mixed, toggle)

    def test_in_the_publication_view_the_offer_is_the_publications(self, client, mixed):
        """ "Sin oferta" there lists MLA2, MLA3 and MLA4: their products are 77 (by MLA4) and 78."""
        assert body(client, mixed, con_oferta="false") == {
            "item_ids": [77, 78],
            "count": 2,
            "sin_producto": 1,
            "fuera_de_catalogo": 0,
        }
        assert body(client, mixed, con_oferta="true") == {
            "item_ids": [77],
            "count": 1,
            "sin_producto": 0,
            "fuera_de_catalogo": 0,
        }

    def test_in_the_producto_view_the_offer_is_the_products(self, client, mixed):
        got = body(client, mixed, con_oferta="false", oferta_por_producto="true")
        assert got == {"item_ids": [78], "count": 1, "sin_producto": 1, "fuera_de_catalogo": 0}


class TestFailClosed:
    def test_over_the_cap_is_a_422_never_a_truncated_set(
        self, client, sold, db, rol_admin, admin_auth_headers, monkeypatch
    ):
        grant(db, rol_admin, VER)
        monkeypatch.setattr(products_service, "MAX_PRODUCT_IDS", 1)
        response = get(client, admin_auth_headers)
        assert response.status_code == 422, response.text
        error = response.json()["error"]
        assert error["code"] == "demasiados_productos" and error["count"] == 2 and error["max"] == 1

    @pytest.mark.parametrize(
        "params, field",
        [({"estado": "bogus"}, "estado"), ({"evento": "price_changed"}, "evento")],  # the events flag is off
    )
    def test_a_bad_filter_is_a_422_naming_it(self, client, sold, db, rol_admin, admin_auth_headers, params, field):
        grant(db, rol_admin, VER)
        response = get(client, admin_auth_headers, **params)
        assert response.status_code == 422 and response.json()["error"]["field"] == field
