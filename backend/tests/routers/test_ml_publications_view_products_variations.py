"""The Producto view with publications that have variations (S12g).

An item with variations is linked per variation only (`links.units_for_item`: no `variation_id = 0` row). Its
products are its live variations' linked products, so it belongs to each of them once and is not "Sin producto".
`/products`, `/items?producto=` / `sin_producto`, `/product-ids` and the groups tree's product level must agree on that
set, as they do for an item-level link.

Seed:
* MLA1: item-level link to 77 (the case that already worked);
* MLA5: two variations, both linked to 77 -> in 77 once, not twice;
* MLA6: one variation linked to 77, one to 78 -> in both;
* MLA7: its only linked variation is gone -> "Sin producto";
* MLA2: no link -> "Sin producto".
"""

# ruff: noqa: F811 -- the imported fixtures are used by name
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import METRICAS, _seller, pg, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

GONE = datetime(2026, 9, 1, tzinfo=timezone.utc)


def fill(conn) -> None:
    seed.add_product(conn, 77, "R77", "Router AX", marca="TP-Link")
    seed.add_product(conn, 78, "R78", "Antena", marca="Ubiquiti")
    for mla in ("MLA1", "MLA2", "MLA5", "MLA6", "MLA7"):
        seed.add_item(conn, mla, status="active")
    seed.add_link(conn, "MLA1", 77)
    for mla, variation_id, product in (("MLA5", 501, 77), ("MLA5", 502, 77), ("MLA6", 601, 77), ("MLA6", 602, 78)):
        seed.add_variation(conn, mla, variation_id)
        seed.add_link(conn, mla, product, variation_id=variation_id)
    seed.add_variation(conn, "MLA7", 701, gone_at=GONE)
    seed.add_link(conn, "MLA7", 78, variation_id=701)


@pytest.fixture()
def seeded(pg, db, rol_admin):
    seed_rows(pg, fill)
    grant(db, rol_admin, VER, METRICAS)
    return pg


def _json(client, headers, endpoint: str, **params) -> dict:
    response = client.get(f"/api/ml-publications/view/{endpoint}", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _items(client, headers, **params) -> list[str]:
    return sorted(i["item_id"] for i in _json(client, headers, "items", limit=100, **params)["items"])


@pytest.mark.postgres
@pytest.mark.usefixtures("seeded")
class TestVariationLinks:
    def test_each_product_counts_its_publications_once_and_sin_producto_only_the_unlinked(
        self, client, admin_auth_headers
    ):
        got = _json(client, admin_auth_headers, "products")

        counts = {row["key"]: row["publications_count"] for row in got["rows"]}
        assert counts == {"77": 3, "78": 1, "0": 2}
        assert got["total"] == 3
        assert got["mla_count"] == 5  # distinct publications, MLA6 once

    def test_opening_a_row_lists_exactly_its_count(self, client, admin_auth_headers):
        assert _items(client, admin_auth_headers, producto="77") == ["MLA1", "MLA5", "MLA6"]
        assert _items(client, admin_auth_headers, producto="78") == ["MLA6"]
        assert _items(client, admin_auth_headers, sin_producto="true") == ["MLA2", "MLA7"]

    def test_product_ids_reach_the_variation_linked_products(self, client, admin_auth_headers):
        got = _json(client, admin_auth_headers, "product-ids")

        assert (got["item_ids"], got["sin_producto"]) == ([77, 78], 2)

    def test_the_groups_tree_puts_a_publication_under_each_of_its_products(self, client, admin_auth_headers):
        # MLA5..MLA7 and MLA2 have no item-level link, so no brand/category: the tree's "__none__" branch.
        got = _json(client, admin_auth_headers, "groups", path="__none__,__none__,__none__")

        leaves = {node["key"]: (node["count"], node["params"]) for node in got["nodes"]}
        assert {key: count for key, (count, _) in leaves.items()} == {"77": 2, "78": 1, "__none__": 2}
        for count, params in leaves.values():  # each leaf opens exactly its count
            assert len(_items(client, admin_auth_headers, **params)) == count
