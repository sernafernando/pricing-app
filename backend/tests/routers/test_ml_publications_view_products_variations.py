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
* MLA8: its only variation's link names no product (`unmatched`) -> "Sin producto";
* MLA2: no link -> "Sin producto".
"""

# ruff: noqa: F811 -- the imported fixtures are used by name
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.equipo import Equipo, ProductoColor
from app.models.producto import ProductoERP
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import METRICAS, _seller, pg, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

GONE = datetime(2026, 9, 1, tzinfo=timezone.utc)
CURRENT = (date.today() - timedelta(days=5), date.today() + timedelta(days=5))


def fill(conn) -> None:
    seed.create_presence_tables(conn)
    seed.add_product(conn, 77, "R77", "Router AX", marca="TP-Link", stock=5)
    seed.add_product(conn, 78, "R78", "Antena", marca="Ubiquiti", stock=8)
    for mla in ("MLA1", "MLA2", "MLA5", "MLA6", "MLA7", "MLA8"):
        seed.add_item(conn, mla, status="active")
    seed.add_link(conn, "MLA1", 77)
    for mla, variation_id, product in (("MLA5", 501, 77), ("MLA5", 502, 77), ("MLA6", 601, 77), ("MLA6", 602, 78)):
        seed.add_variation(conn, mla, variation_id)
        seed.add_link(conn, mla, product, variation_id=variation_id)
    seed.add_variation(conn, "MLA7", 701, gone_at=GONE)
    seed.add_link(conn, "MLA7", 78, variation_id=701)
    seed.add_variation(conn, "MLA8", 801)
    seed.add_link(conn, "MLA8", None, variation_id=801, match_status="unmatched")


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
        assert counts == {"77": 3, "78": 1, "0": 3}
        assert got["total"] == 3
        assert got["mla_count"] == 6  # distinct publications, MLA6 once

    def test_a_product_row_has_its_erp_stock_and_sin_producto_none(self, client, admin_auth_headers):
        got = _json(client, admin_auth_headers, "products")

        assert {row["key"]: row["stock"] for row in got["rows"]} == {"77": 5, "78": 8, "0": None}

    def test_opening_a_row_lists_exactly_its_count(self, client, admin_auth_headers):
        assert _items(client, admin_auth_headers, producto="77") == ["MLA1", "MLA5", "MLA6"]
        assert _items(client, admin_auth_headers, producto="78") == ["MLA6"]
        assert _items(client, admin_auth_headers, sin_producto="true") == ["MLA2", "MLA7", "MLA8"]

    def test_product_ids_reach_the_variation_linked_products(self, client, admin_auth_headers):
        got = _json(client, admin_auth_headers, "product-ids")

        assert (got["item_ids"], got["sin_producto"]) == ([77, 78], 3)

    def test_the_groups_tree_puts_a_publication_under_each_of_its_products(self, client, admin_auth_headers):
        leaves: dict[str, int] = {}
        pending: list[list[str]] = [[]]
        while pending:
            path = pending.pop()
            for node in _json(client, admin_auth_headers, "groups", path=",".join(path))["nodes"]:
                if node["kind"] != "producto":
                    pending.append([*path, node["key"]])
                    continue
                leaves[node["key"]] = leaves.get(node["key"], 0) + node["count"]
                # each leaf opens exactly its count
                assert len(_items(client, admin_auth_headers, **node["params"])) == node["count"]

        assert leaves == {"77": 3, "78": 1, "__none__": 3}


@pytest.fixture()
def painted(db) -> None:
    """Global layer: 77 rojo, 78 azul (the colors live next to the application's own catalog)."""
    global_id = db.query(Equipo).filter(Equipo.es_global.is_(True)).one().id
    db.add_all(ProductoERP(item_id=item_id, codigo=f"C{item_id}", descripcion=f"P{item_id}") for item_id in (77, 78))
    db.flush()
    db.add_all(ProductoColor(equipo_id=global_id, item_id=i, color_ml=c) for i, c in ((77, "rojo"), (78, "azul")))
    db.flush()


@pytest.mark.postgres
@pytest.mark.usefixtures("seeded")
class TestVariationLinksInTheProductFilters:
    """Color and mejor oferta are the PRODUCT's: a publication linked per variation has its variations' products."""

    @pytest.mark.usefixtures("painted")
    def test_the_color_filter_reaches_the_variation_linked_products(self, client, admin_auth_headers):
        assert _items(client, admin_auth_headers, colores="rojo") == ["MLA1", "MLA5", "MLA6"]
        assert _items(client, admin_auth_headers, colores="sin_color") == ["MLA2", "MLA7", "MLA8"]

        counts = {
            r["key"]: r["publications_count"]
            for r in _json(client, admin_auth_headers, "products", colores="rojo")["rows"]
        }
        assert counts["77"] == 3

    @pytest.mark.usefixtures("painted")
    def test_a_publication_with_a_painted_and_an_unpainted_product_is_in_both_color_sets(
        self, db, client, admin_auth_headers
    ):
        db.query(ProductoColor).filter(ProductoColor.item_id == 78).delete()
        db.flush()

        # MLA6 is linked per variation to 77 (rojo) and 78 (no color now)
        assert _items(client, admin_auth_headers, colores="rojo") == ["MLA1", "MLA5", "MLA6"]
        assert _items(client, admin_auth_headers, colores="sin_color") == ["MLA2", "MLA6", "MLA7", "MLA8"]

    def test_a_variation_linked_publication_s_offer_is_its_product_s(self, pg, client, admin_auth_headers):
        seed_rows(pg, lambda conn: seed.add_oferta(conn, "MLA5", *CURRENT, precio_final=900, pvp_seller=950))

        # Producto view: mejor oferta of the PRODUCT -- 77 has one through MLA5, so every 77 publication counts
        counts = {
            r["key"]: r["publications_count"]
            for r in _json(client, admin_auth_headers, "products", con_oferta="true")["rows"]
        }
        assert counts["77"] == 3
        assert _items(client, admin_auth_headers, con_oferta="true", oferta_por_producto="true") == [
            "MLA1",
            "MLA5",
            "MLA6",
        ]

    def test_the_brand_is_the_linked_product_s(self, client, admin_auth_headers):
        # MLA5/MLA6 are linked per variation only: their brand is their (first) variation product's, 77 TP-Link
        assert _items(client, admin_auth_headers, marcas="TP-LINK") == ["MLA1", "MLA5", "MLA6"]
        assert _items(client, admin_auth_headers, q="Router") == ["MLA1", "MLA5", "MLA6"]  # the product's name too
        roots = {n["key"]: n["count"] for n in _json(client, admin_auth_headers, "groups")["nodes"]}
        assert roots == {"TP-LINK": 3, "__none__": 3}
