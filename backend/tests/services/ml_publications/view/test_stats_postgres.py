"""S12d4: Productos' stat cards over the Publicaciones ML filters (`stats.compute`, `GET /view/stats`).

Each card counts the linked products a click on it would list: the screen's current filters plus the card's own
filter (Productos' `aplicarFiltroStat`). So every count is checked against the products that very filter selects
(`products.product_ids`, the Producto view's rows), never against a hand count. A publication with no product
counts in no card, as no product filter lists it.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.services.ml_publications.view import products, stats
from app.services.ml_publications.view.filters import parse_filter
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_listing_postgres import conn, db  # noqa: F401

pytestmark = pytest.mark.postgres

TODAY = date.today()

# Each card and the filter its click applies, as `parse_filter` params (the frontend's URL keys map onto them).
CARDS = {
    "total": {},
    "con_stock": {"stock": "erp_con_stock"},
    "con_precio": {"con_precio": True},
    "con_stock_sin_precio": {"stock": "erp_con_stock", "con_precio": False},
    "nuevos": {"nuevos_ultimos_7_dias": True},
    "nuevos_sin_precio": {"nuevos_ultimos_7_dias": True, "con_precio": False},
    "oferta_sin_rebate": {"con_oferta": True, "con_rebate": False},
}
MARKUP_CARDS = {
    "markup_negativo_clasica": {"markup_clasica_positivo": False},
    "markup_negativo_rebate": {"markup_rebate_positivo": False},
    "markup_negativo_oferta": {"markup_oferta_positivo": False},
    "markup_negativo_web": {"markup_web_transf_positivo": False},
}
# Productos' "Sin MLA" card (S12d4c): the products no publication is linked to, under the product filters.
SIN_MLA_CARDS = {
    "sin_mla": {},
    "sin_mla_con_stock": {"stock": "erp_con_stock"},
    "sin_mla_sin_stock": {"stock": "erp_sin_stock"},
    "sin_mla_nuevos": {"nuevos_ultimos_7_dias": True},
}


@pytest.fixture(autouse=True)
def rows(conn) -> None:
    seed.create_presence_tables(conn, with_pricing=True)
    conn.execute(text(seed.MARKUP_DDL))
    seed.add_product(conn, 70, "A1", "Router", marca="TP-Link", stock=5)
    seed.add_product(conn, 71, "B1", "Camara", marca="Hikvision", stock=0)
    seed.add_product(conn, 72, "C1", "Switch", marca="TP-Link", stock=3)  # no pricing row: "sin precio"
    seed.add_product(conn, 73, "D1", "Antena", marca="TP-Link", stock=2)
    seed.add_product(conn, 74, "E1", "Cable", marca="TP-Link", stock=4)  # no publication: Sin MLA, new
    seed.add_product(conn, 75, "F1", "Fuente", marca="Kabel", stock=0)  # no publication: Sin MLA, not new
    for mla in ("MLA1", "MLA2", "MLA3", "MLA4", "MLA5", "MLA6", "MLA7"):
        seed.add_item(conn, mla, status="active")
    seed.add_link(conn, "MLA1", 70)
    seed.add_link(conn, "MLA5", 70)  # a second publication of 70: still one product
    seed.add_link(conn, "MLA2", 71)
    seed.add_link(conn, "MLA3", 72)
    seed.add_link(conn, "MLA6", 73)  # MLA4: no product
    seed.add_link(conn, "MLA7", 71)  # 71's second publication, with no offer of its own
    seed.add_pricing(conn, 70, precio_lista_ml=1000, participa_rebate=True, markup_calculado=-2, markup_rebate=5)
    seed.add_pricing(conn, 71, precio_lista_ml=900, participa_rebate=False, markup_calculado=-1, markup_oferta=-3)
    seed.add_pricing(conn, 73, precio_lista_ml=None, participa_rebate=False, markup_web_real=-4)
    for mla in ("MLA1", "MLA2"):  # current offers with a seller price: 70 (rebate) and 71 (no rebate)
        seed.add_oferta(conn, mla, TODAY - timedelta(days=5), TODAY + timedelta(days=5), pvp_seller=86486)
    conn.execute(text("UPDATE productos_erp SET fecha_sync = now() - interval '8 days' WHERE item_id IN (70, 71, 75)"))


def listed_products(db, **params) -> int:
    return len(products.product_ids(db, parse_filter(**params)).item_ids)


class TestEachCardCountsWhatItsClickLists:
    @pytest.mark.parametrize("current", [{}, {"marcas": "TP-Link"}, {"estado": "active", "q": "MLA1"}])
    def test_every_card_matches_its_filter_over_the_current_filters(self, db, current) -> None:
        got = stats.compute(db, parse_filter(**current), markups=True)
        expected = {card: listed_products(db, **current, **extra) for card, extra in {**CARDS, **MARKUP_CARDS}.items()}
        assert got == expected

    def test_the_counts_of_the_seed(self, db) -> None:
        got = stats.compute(db, parse_filter(), markups=True)
        assert got == {
            "total": 4,  # MLA4 has no product; 70's two publications count once
            "con_stock": 3,
            "con_precio": 2,
            "con_stock_sin_precio": 2,  # 72 (no pricing row) and 73 (no list price)
            "nuevos": 2,
            "nuevos_sin_precio": 2,
            "oferta_sin_rebate": 1,  # 71; 70's offer is on rebate
            "markup_negativo_clasica": 2,
            "markup_negativo_rebate": 0,
            "markup_negativo_oferta": 1,
            "markup_negativo_web": 1,
        }

    def test_the_producto_view_asks_the_offer_of_the_product(self, db) -> None:
        # MLA7 has no offer, its product 71 has one (on MLA2): only the Producto view's card counts it.
        by_product = {"oferta_por_producto": True, "q": "MLA7"}
        by_publication = {"q": "MLA7"}
        assert stats.compute(db, parse_filter(**by_product), markups=False)["oferta_sin_rebate"] == 1
        assert stats.compute(db, parse_filter(**by_publication), markups=False)["oferta_sin_rebate"] == 0
        for current in (by_product, by_publication):
            got = stats.compute(db, parse_filter(**current), markups=False)
            assert got["oferta_sin_rebate"] == listed_products(db, **current, **CARDS["oferta_sin_rebate"])


class TestMarkups:
    def test_without_markups_the_markup_cards_are_absent(self, db) -> None:
        assert set(stats.compute(db, parse_filter(), markups=False)) == set(CARDS)


class TestEmpty:
    def test_an_empty_selection_counts_zero_everywhere(self, db) -> None:
        got = stats.compute(db, parse_filter(q="nothing like this"), markups=True)
        assert set(got.values()) == {0}


class TestSinMla:
    @pytest.mark.parametrize("current", [{}, {"marcas": "TP-Link"}, {"oferta_por_producto": True}])
    def test_each_sin_mla_card_matches_its_list(self, db, current) -> None:
        got = stats.compute(db, parse_filter(**current), markups=False, sin_mla=True)
        for card, extra in SIN_MLA_CARDS.items():
            assert got[card] == listed_products(db, con_mla=False, **current, **extra), card

    def test_the_sin_mla_counts_of_the_seed(self, db) -> None:
        got = stats.compute(db, parse_filter(), markups=False, sin_mla=True)
        assert {card: got[card] for card in SIN_MLA_CARDS} == {
            "sin_mla": 2,  # 74 and 75; the linked products are not "sin MLA"
            "sin_mla_con_stock": 1,
            "sin_mla_sin_stock": 1,
            "sin_mla_nuevos": 1,
        }

    def test_only_asked_and_never_with_a_publication_filter(self, db) -> None:
        assert set(stats.compute(db, parse_filter(), markups=False)) == set(CARDS)
        assert set(stats.compute(db, parse_filter(estado="active"), markups=False, sin_mla=True)) == set(CARDS)

    def test_with_sin_mla_on_the_cards_count_the_sin_mla_products(self, db) -> None:
        got = stats.compute(db, parse_filter(con_mla=False), markups=True, sin_mla=True)
        assert got["total"] == 2 and got["oferta_sin_rebate"] == 0
        for card, extra in {**CARDS, **MARKUP_CARDS}.items():
            if card != "oferta_sin_rebate":  # an offer is a publication's: refused with Sin MLA
                assert got[card] == listed_products(db, con_mla=False, **extra), card
