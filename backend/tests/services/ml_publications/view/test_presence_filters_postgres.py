"""S5: Productos' "Filtros de Presencia" on the Publicaciones ML list (`/view/items`, and so `/view/products`).

The same params and meaning as `GET /productos`: rebate, web transferencia and out of cards are flags of the
LINKED product's `productos_pricing` row (no row reads "sin"); Tienda Nube is the product's active variants; mejor
oferta is a current `ofertas_ml` row of the publication itself (Productos asks it of any MLA of the product, which is
what the Producto view gives back). A publication without a linked product matches neither side of a product flag.
Row shapes follow production rows (product 3163's flags, product 1123 / 983's Tienda Nube variants, the latest
`ofertas_ml` row).
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.ml_publications.view import listing
from app.services.ml_publications.view.filters import parse_filter
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_listing_postgres import conn, db, ids  # noqa: F401

pytestmark = pytest.mark.postgres

TODAY = date.today()


def run(db, **params):
    return listing.list_items(db, parse_filter(**params), listing.parse_sort(None, None), 50, 0, events=True)


def listed(db, **params) -> list[str]:
    page = run(db, **params)
    assert page.total == len(page.items)
    return sorted(ids(page))


@pytest.fixture(autouse=True)
def rows(conn) -> None:  # noqa: F811
    seed.create_presence_tables(conn, with_pricing=True)
    seed.add_product(conn, 70, "A1", "Router", marca="TP-Link", stock=5)
    seed.add_product(conn, 71, "B1", "Camara", marca="Hikvision", stock=0)
    seed.add_product(conn, 72, "C1", "Switch", marca="TP-Link", stock=3)  # no pricing row, not in Tienda Nube
    for mla in ("MLA1", "MLA2", "MLA3", "MLA4", "MLA5"):
        seed.add_item(conn, mla, status="active")
    seed.add_link(conn, "MLA1", 70)
    seed.add_link(conn, "MLA5", 70)  # a second publication of the same product
    seed.add_link(conn, "MLA2", 71)
    seed.add_link(conn, "MLA3", 72)  # MLA4: no product
    seed.add_pricing(conn, 70, participa_rebate=True, participa_web_transferencia=True, out_of_cards=True)
    seed.add_pricing(conn, 71, participa_rebate=False, participa_web_transferencia=True, out_of_cards=False)
    # two active variants of 70, both on sale: the publication is still listed once
    seed.add_tn_variant(conn, 70, 1182988920, price=167021, promotional_price=93380, activo=True)
    seed.add_tn_variant(conn, 70, 1182988921, price=167021, promotional_price=93380, activo=True)
    seed.add_tn_variant(conn, 71, 1182984711, price=22231, promotional_price=None, activo=True)
    seed.add_tn_variant(conn, 72, 1182984712, price=1000, promotional_price=500, activo=False)  # gone from TN
    seed.add_oferta(
        conn, "MLA1", TODAY - timedelta(days=5), TODAY + timedelta(days=5), precio_final=83200, pvp_seller=86486
    )
    seed.add_oferta(conn, "MLA2", date(2026, 5, 8), date(2026, 5, 31), precio_final=83200, pvp_seller=86486)  # over
    seed.add_oferta(conn, "MLA3", TODAY, TODAY, precio_final=83200, pvp_seller=None)  # no seller price: not one


class TestProductFlags:
    def test_rebate(self, db) -> None:
        assert listed(db, con_rebate=True) == ["MLA1", "MLA5"]
        assert listed(db, con_rebate=False) == ["MLA2", "MLA3"]  # 72 has no pricing row: "sin"

    def test_web_transferencia(self, db) -> None:
        assert listed(db, con_web_transf=True) == ["MLA1", "MLA2", "MLA5"]
        assert listed(db, con_web_transf=False) == ["MLA3"]

    def test_out_of_cards(self, db) -> None:
        assert listed(db, out_of_cards=True) == ["MLA1", "MLA5"]
        assert listed(db, out_of_cards=False) == ["MLA2", "MLA3"]

    def test_a_publication_without_a_product_matches_neither_side(self, db) -> None:
        for param in ("con_rebate", "con_web_transf", "out_of_cards"):
            assert "MLA4" not in listed(db, **{param: True}) + listed(db, **{param: False})


class TestMejorOferta:
    def test_a_current_offer_with_a_seller_price_of_the_publication(self, db) -> None:
        assert listed(db, con_oferta=True) == ["MLA1"]
        assert listed(db, con_oferta=False) == ["MLA2", "MLA3", "MLA4", "MLA5"]


class TestTiendaNube:
    def test_con_descuento_lists_each_publication_once(self, db) -> None:
        assert listed(db, tn_con_descuento=True) == ["MLA1", "MLA5"]

    def test_sin_descuento(self, db) -> None:
        assert listed(db, tn_sin_descuento=True) == ["MLA2"]

    def test_no_publicado_is_in_stock_and_not_active_in_tienda_nube(self, db) -> None:
        assert listed(db, tn_no_publicado=True) == ["MLA3"]  # 71 has no stock; MLA4 has no product


class TestWithTheOtherFilters:
    def test_toggles_and_with_each_other_and_the_product_filters(self, db) -> None:
        assert listed(db, con_rebate=False, marcas="tp-link") == ["MLA3"]
        assert listed(db, con_web_transf=True, out_of_cards=False) == ["MLA2"]
        assert listed(db, con_rebate=True, con_oferta=True) == ["MLA1"]
