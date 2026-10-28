"""#1870 follow-up (draft): brand, category, subcategory and PM over ANY linked product.

Color, offer, the presence toggles and `q` already test every product a publication is linked to (#1870). Brand,
category, subcategory and PM still read ONE product per publication (`filters.primary_product`), which is the
lowest-id product of a publication linked per variation only. A publication whose variations are products of
different brands therefore disagrees with itself across the views. The verifier's reproducer, on the #1870 world
(`fill_siblings`): VA6 has variations linked to 77 (TP-Link, not painted) and 78 (Ubiquiti, painted rojo).

These tests pin consistency, not a tree-count design: how a publication under two brands counts in the tree is the
owner's decision. They are strict `xfail`: the suite stays green, and the fix that makes them pass must drop the
marker (a strict xfail that passes fails the run).
"""

# ruff: noqa: F811 -- the imported fixtures are used by name
from __future__ import annotations

import pytest

from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_products_variations import _items, _json, _rows, siblings  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401


def _opened(client, headers, **params) -> list[str]:
    """The publications the Producto view's rows open (`/items?producto=K` under the same filters), each once."""
    keys = [r["key"] for r in _json(client, headers, "products", **params)["rows"]]
    return sorted({item for key in keys for item in _items(client, headers, producto=key, **params)})


def _walk(client, headers, path: tuple[str, ...] = (), **params):
    """Every node of the groups tree under `params`, with its path."""
    page = _json(client, headers, "groups", path=",".join(path), **params) if path else None
    nodes = (page or _json(client, headers, "groups", **params))["nodes"]
    for node in nodes:
        yield path, node
        if not node["leaf"]:
            yield from _walk(client, headers, (*path, node["key"]), **params)


@pytest.mark.postgres
@pytest.mark.usefixtures("siblings")
@pytest.mark.xfail(
    strict=True, reason="brand, category, subcategory and PM still read the primary product (#1870 follow-up)"
)
class TestAPublicationOfTwoBrandsIsTheSameInEveryView:
    def test_items_and_the_producto_view_keep_the_same_publications_under_brand_and_color(
        self, client, admin_auth_headers
    ):
        # /items lists VA6 (brand on its primary 77, color on its 78); no single product passes both, so the
        # Producto view, /product-ids and the export are empty
        params = {"marcas": "TP-LINK", "colores": "rojo"}
        assert _opened(client, admin_auth_headers, **params) == _items(client, admin_auth_headers, **params)

    def test_a_brand_filter_finds_a_publication_by_any_of_its_products(self, client, admin_auth_headers):
        # VA6's 78 is Ubiquiti: the 78 row has 3 publications by name (q=R78) but only 2 by its own brand
        assert _rows(client, admin_auth_headers, marcas="UBIQUITI") == _rows(client, admin_auth_headers, q="R78")
        assert "VA6" in _items(client, admin_auth_headers, marcas="UBIQUITI")

    def test_a_product_s_leaf_in_the_tree_holds_what_its_producto_row_holds(self, client, admin_auth_headers):
        # VA6 hangs under its primary product's brand (TP-LINK > REDES), so 78's leaf under UBIQUITI has 2, not 3
        leaves = {node["key"]: node["count"] for _path, node in _walk(client, admin_auth_headers) if node["leaf"]}
        assert leaves["78"] == _rows(client, admin_auth_headers)["78"]

    def test_no_group_node_is_a_dead_end(self, client, admin_auth_headers):
        # with colores=rojo, TP-LINK > REDES > Sin subcategoria counts VA6 and opens to no product node
        dead = []
        for path, node in _walk(client, admin_auth_headers, colores="rojo"):
            if node["leaf"] or node["count"] == 0:
                continue
            children = _json(client, admin_auth_headers, "groups", path=",".join((*path, node["key"])), colores="rojo")
            if not children["nodes"]:
                dead.append((*path, node["key"]))
        assert dead == []
