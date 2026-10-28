"""`GET /api/ml-publications/view/product-ids` with the markup filters (`markup_neg`, `markup_min`, `markup_max`).

Filtering the negative (or out-of-range) markups and fixing them in bulk is the main use of the bulk actions, so the
resolver applies the markup filter exactly as `/items` does: the SAME post-query step (`listing.markup_accepted`),
over the whole filtered set. The contract: the products it returns are the distinct linked products of every
publication `/items` lists under the same filters, paged to the end.

Same harness as `test_ml_publications_view_markup.py` (stubbed pricing context and shipping batch).
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest

from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import GANANCIA, VER, seed_rows
from tests.routers.test_ml_publications_view_markup import fill, pg, pricing, view_pg, worst_of  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

URL = "/api/ml-publications/view/product-ids"
ITEMS_URL = "/api/ml-publications/view/items"


def gone(conn) -> None:
    """MLA7: a negative publication linked to product 99, which is no longer in the ERP catalog."""
    seed.add_item(conn, "MLA7", title="Golf", listing_type_id="gold_pro", tags=["9x_campaign"], price=90000)
    seed.add_sale_price(conn, "MLA7", 100000)
    seed.add_link(conn, "MLA7", 99)


@pytest.fixture()
def analyst(client, pg, db, rol_admin, admin_auth_headers):  # noqa: F811
    seed_rows(pg, fill)
    grant(db, rol_admin, VER, GANANCIA)
    return admin_auth_headers


def resolve(client, headers, **params) -> dict:
    response = client.get(URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def listed(client, headers, **params) -> list[dict]:
    """Every row `/items` lists for `params`, paged to the end."""
    rows: list[dict] = []
    while True:
        response = client.get(ITEMS_URL, headers=headers, params={**params, "limit": 2, "offset": len(rows)})
        assert response.status_code == 200, response.text
        page = response.json()
        rows += page["items"]
        if len(rows) >= page["total"]:
            return rows


# The products a publication linked per variation only is linked to (`fill`): `/items`' `link` is the item-level one.
VARIATION_PRODUCTS = {"MLA4": {70, 71}}


def products_of(row: dict) -> set[int]:
    item_level = row["link"]["producto_item_id"]
    return {item_level} if item_level is not None else VARIATION_PRODUCTS.get(row["item_id"], set())


MARKUP_PARAMS = [
    {"markup_neg": "true"},
    {"markup_min": "0"},
    {"markup_max": "0"},
    {"markup_min": str(round(worst_of(72) - 1, 2)), "markup_max": str(round(worst_of(73) + 1, 2))},
]


class TestMarkupFilter:
    @pytest.mark.parametrize("params", MARKUP_PARAMS, ids=lambda p: "&".join(f"{k}={v}" for k, v in p.items()))
    def test_the_products_are_those_of_the_publications_items_lists(self, client, analyst, pricing, params) -> None:
        # a product is in the set when `/items?producto=<it>` lists a publication: its units of that product pass
        rows = listed(client, analyst, **params)
        candidates = set().union(*(products_of(r) for r in listed(client, analyst)))
        linked = sorted(p for p in candidates if listed(client, analyst, producto=str(p), **params))
        got = resolve(client, analyst, **params)
        assert (got["item_ids"], got["count"]) == (linked, len(linked))
        assert got["sin_producto"] == sum(1 for r in rows if not products_of(r))

    def test_markup_neg_keeps_only_the_negative_products(self, client, analyst, pricing) -> None:
        # 71 (MLA2) and 72 (MLA5) are negative. MLA4 is linked per variation to 70 (positive unit) and 71 (negative):
        # only 71 is negative through it -- 70's own units are all positive, so a bulk action never reprices it.
        assert resolve(client, analyst, markup_neg="true") == {
            "item_ids": [71, 72],
            "count": 2,
            "sin_producto": 0,
            "fuera_de_catalogo": 0,
        }

    def test_without_ver_ganancia_the_markup_filters_are_403(self, client, pg, db, rol_admin, admin_auth_headers):  # noqa: F811
        seed_rows(pg, fill)
        grant(db, rol_admin, VER)
        response = client.get(URL, headers=admin_auth_headers, params={"markup_neg": "true"})
        assert response.status_code == 403 and GANANCIA in response.json()["error"]["message"]

    def test_a_bad_bound_is_a_422_naming_it(self, client, analyst, pricing) -> None:
        response = client.get(URL, headers=analyst, params={"markup_min": "5", "markup_max": "1"})
        assert response.status_code == 422 and response.json()["error"]["field"] == "markup_min"


class TestOutOfCatalog:
    def test_a_linked_product_gone_from_the_catalog_is_left_out_and_counted(
        self,
        client,
        pg,
        analyst,
        pricing,  # noqa: F811
    ) -> None:
        seed_rows(pg, gone)
        got = resolve(client, analyst, q="Golf")
        assert got == {"item_ids": [], "count": 0, "sin_producto": 0, "fuera_de_catalogo": 1}
