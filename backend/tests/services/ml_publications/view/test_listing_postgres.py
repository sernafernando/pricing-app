"""P5.T2-T4: the list query of `/ml-publications/view/items` on Postgres (rows, filters, search, sorts, paging, facets).

Runs over the real store migrations in a throwaway schema (`env`: core, sub-resources, product links, quality,
stock locations, plus the `productos_erp` table built from the model). Rows are plain inserts (`seed.py`).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.services.ml_publications.view import listing
from app.services.ml_publications.view.filters import FilterError, parse_filter
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres


STORES_DDL = (
    "CREATE TABLE ml_tiendas_oficiales (store_id bigint PRIMARY KEY, nombre varchar(100) NOT NULL, "
    "clave varchar(50), orden integer NOT NULL DEFAULT 0, activa boolean NOT NULL DEFAULT true)"
)


@pytest.fixture()
def conn(env):  # noqa: F811
    """An autocommit connection for seeding (the service reads through its own session), plus the display-name
    table of the official stores, which lives in the application database next to the store."""
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(STORES_DDL))
        yield connection


@pytest.fixture()
def db(env, conn):  # noqa: F811
    session = sessionmaker(bind=env, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def run(db: Session, *, limit: int = 50, offset: int = 0, events: bool = True, orden=None, direction=None, **params):
    return listing.list_items(
        db, parse_filter(**params), listing.parse_sort(orden, direction), limit, offset, events=events
    )


def ids(page) -> list[str]:
    return [row["item_id"] for row in page.items]


class TestOneRowPerMla:
    def test_a_classic_item_with_four_variations_is_one_row_with_a_count_of_four(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", title="Zapatilla")
        for variation_id in (11, 12, 13, 14):
            seed.add_variation(conn, "MLA1", variation_id)
        seed.add_variation(conn, "MLA1", 15, gone_at=seed.NOW)  # a variation ML dropped is not counted
        seed.add_item(conn, "MLA2", title="Sin variaciones")
        page = run(db)
        by_id = {row["item_id"]: row for row in page.items}
        assert sorted(by_id) == ["MLA1", "MLA2"] and page.total == 2
        assert by_id["MLA1"]["variations_count"] == 4
        assert by_id["MLA2"]["variations_count"] == 0

    def test_two_items_of_the_same_family_are_two_rows(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", family_id=900, user_product_id="MLAU1", family_name="Familia")
        seed.add_item(conn, "MLA2", family_id=900, user_product_id="MLAU2", family_name="Familia")
        page = run(db)
        assert sorted(ids(page)) == ["MLA1", "MLA2"]
        assert {row["family_id"] for row in page.items} == {900}

    def test_the_row_carries_the_item_fields_the_screen_shows(self, conn, db) -> None:
        seed.add_item(
            conn,
            "MLA1",
            title="Router",
            thumbnail="http://t/1.jpg",
            permalink="http://p/1",
            status="active",
            sub_status=["out_of_stock"],
            listing_type_id="gold_pro",
            catalog_listing=True,
            logistic_type="fulfillment",
            official_store_id=2645,
            brand="TP-Link",
            family_id=7,
            family_name="Archer",
            user_product_id="MLAU1",
            last_trigger_received_at=seed.NOW,
        )
        (row,) = run(db).items
        assert row["title"] == "Router" and row["thumbnail"] == "http://t/1.jpg" and row["permalink"] == "http://p/1"
        assert row["status"] == "active" and row["sub_status"] == ["out_of_stock"]
        assert row["listing_type_id"] == "gold_pro" and row["catalog_listing"] is True
        assert row["logistic_type"] == "fulfillment" and row["is_full"] is True
        assert row["official_store_id"] == 2645 and row["ml_brand"] == "TP-Link"
        assert (row["family_id"], row["family_name"], row["user_product_id"]) == (7, "Archer", "MLAU1")
        assert row["last_activity_at"] == seed.NOW
        assert row["gone"] is False

    def test_is_full_is_false_for_any_other_logistic_type_and_for_none(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", logistic_type="cross_docking")
        seed.add_item(conn, "MLA2")
        assert {row["item_id"]: row["is_full"] for row in run(db).items} == {"MLA1": False, "MLA2": False}


class TestLinkedProduct:
    def test_an_unlinked_item_is_listed_with_null_product_columns(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", title="Sin evaluar")
        seed.add_item(conn, "MLA2", title="Sin producto")
        seed.add_link(conn, "MLA2", None, source="manual_none", match_status="no_product")
        page = run(db)
        by_id = {row["item_id"]: row["link"] for row in page.items}
        assert page.total == 2
        assert by_id["MLA1"] == {
            "state": "no_evaluado",
            "producto_item_id": None,
            "codigo": None,
            "descripcion": None,
            "marca": None,
        }
        assert by_id["MLA2"]["state"] == "sin_producto" and by_id["MLA2"]["descripcion"] is None

    def test_a_linked_item_carries_the_product_and_its_link_state(self, conn, db) -> None:
        seed.add_product(conn, 70, "7790001", "Router AC1200", marca="TP-Link", categoria="Redes")
        seed.add_product(conn, 71, "7790002", "Switch 8p", marca="TP-Link", categoria="Redes")
        seed.add_item(conn, "MLA1")
        seed.add_item(conn, "MLA2")
        seed.add_item(conn, "MLA3")
        seed.add_link(conn, "MLA1", 70)
        seed.add_link(conn, "MLA2", 71, source="manual")
        seed.add_link(conn, "MLA3", None, match_status="conflict")
        by_id = {row["item_id"]: row["link"] for row in run(db).items}
        assert by_id["MLA1"] == {
            "state": "auto",
            "producto_item_id": 70,
            "codigo": "7790001",
            "descripcion": "Router AC1200",
            "marca": "TP-Link",
        }
        assert by_id["MLA2"]["state"] == "manual" and by_id["MLA2"]["producto_item_id"] == 71
        assert by_id["MLA3"]["state"] == "conflicto" and by_id["MLA3"]["producto_item_id"] is None

    def test_only_the_item_level_link_counts(self, conn, db) -> None:
        seed.add_product(conn, 70, "7790001", "Router")
        seed.add_item(conn, "MLA1")
        seed.add_link(conn, "MLA1", 70, variation_id=11)  # a variation-level link is not the item's
        (row,) = run(db).items
        assert row["link"]["state"] == "no_evaluado" and row["link"]["codigo"] is None

    def test_a_link_to_a_vanished_product_is_still_one_row(self, conn, db) -> None:
        seed.add_item(conn, "MLA1")
        seed.add_link(conn, "MLA1", 999)  # productos_erp has no item 999: the link dangles
        page = run(db)
        assert ids(page) == ["MLA1"] and page.total == 1
        assert page.items[0]["link"]["codigo"] is None


class TestPrice:
    def test_a_sale_price_wins_over_the_item_price(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", price=1000)
        seed.add_sale_price(conn, "MLA1", 900, regular_amount=1000, promotion_type="deal", campaign_id="C1")
        (row,) = run(db).items
        assert row["price"] == {
            "amount": 900,
            "source": "sale_price",
            "regular_amount": 1000,
            "promotion_type": "deal",
            "campaign": "C1",
            "pricelist_id": None,
        }

    def test_without_a_sale_price_the_item_price_is_used(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", price=1000)
        (row,) = run(db).items
        assert row["price"]["amount"] == 1000 and row["price"]["source"] == "item_price"
        assert row["price"]["regular_amount"] is None

    def test_a_failed_or_gone_sale_price_row_is_ignored(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", price=1000)
        seed.add_sale_price(conn, "MLA1", 1, http_status=404)
        seed.add_item(conn, "MLA2", price=2000)
        seed.add_sale_price(conn, "MLA2", 2, gone_at=seed.NOW)
        assert {r["item_id"]: r["price"]["source"] for r in run(db).items} == {
            "MLA1": "item_price",
            "MLA2": "item_price",
        }

    def test_no_price_at_all_is_null_with_no_source(self, conn, db) -> None:
        seed.add_item(conn, "MLA1")
        (row,) = run(db).items
        assert row["price"]["amount"] is None and row["price"]["source"] is None


class TestStoreLabel:
    def test_the_label_is_the_configured_name_or_null(self, conn, db) -> None:
        conn.execute(text("INSERT INTO ml_tiendas_oficiales (store_id, nombre) VALUES (2645, 'TP-Link')"))
        seed.add_item(conn, "MLA1", official_store_id=2645)
        seed.add_item(conn, "MLA2", official_store_id=999)  # a store nobody named
        seed.add_item(conn, "MLA3")
        assert {row["item_id"]: row["store_label"] for row in run(db).items} == {
            "MLA1": "TP-Link",
            "MLA2": None,
            "MLA3": None,
        }


class TestStock:
    def test_full_stock_is_null_without_a_stock_row_never_zero(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", user_product_id="MLAU1", available_quantity=4)
        seed.add_item(conn, "MLA2", available_quantity=0)  # no user product at all
        by_id = {row["item_id"]: row["stock"] for row in run(db).items}
        assert by_id["MLA1"] == {"available": 4, "full": None, "own": None, "as_of": None}
        assert by_id["MLA2"] == {"available": 0, "full": None, "own": None, "as_of": None}

    def test_a_stock_row_gives_the_split_and_a_real_zero_stays_zero(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", user_product_id="MLAU1", available_quantity=9)
        seed.add_item(conn, "MLA2", user_product_id="MLAU2", available_quantity=0)
        seed.add_item(conn, "MLA3", user_product_id="MLAU3")
        seed.add_stock(conn, "MLAU1", full=6, own=3)
        seed.add_stock(conn, "MLAU2", full=0, own=0)
        seed.add_stock(conn, "MLAU3", full=None, own=None, ml_last_updated=None)  # no readable locations list
        by_id = {row["item_id"]: row["stock"] for row in run(db).items}
        assert by_id["MLA1"] == {"available": 9, "full": 6, "own": 3, "as_of": seed.NOW}
        assert (by_id["MLA2"]["full"], by_id["MLA2"]["own"]) == (0, 0)
        assert (by_id["MLA3"]["full"], by_id["MLA3"]["own"]) == (None, None)


class TestGone:
    def test_gone_items_are_hidden_by_default_and_never_existed_items_always(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", status="active")
        seed.add_item(conn, "MLA2", status="closed", gone_at=seed.NOW)
        seed.add_item(conn, "MLA3", never_existed=True)
        page = run(db)
        assert ids(page) == ["MLA1"] and page.total == 1
        assert ids(run(db, estado="gone")) == ["MLA2"]

    def test_a_gone_item_is_flagged_when_it_is_asked_for(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", status="active")
        seed.add_item(conn, "MLA2", status="closed", gone_at=seed.NOW)
        rows = {row["item_id"]: row for row in run(db, estado="active,gone").items}
        assert sorted(rows) == ["MLA1", "MLA2"]
        assert rows["MLA2"]["gone"] is True and rows["MLA2"]["gone_at"] == seed.NOW
        assert rows["MLA1"]["gone"] is False and rows["MLA1"]["gone_at"] is None

    def test_items_without_a_status_are_selected_and_excluded_by_their_own_token(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", status="active")
        seed.add_item(conn, "MLA2", status=None)
        seed.add_item(conn, "MLA3", status="closed")
        assert ids(run(db, estado="sin_estado")) == ["MLA2"]
        assert sorted(ids(run(db, estado="sin_estado,closed"))) == ["MLA2", "MLA3"]
        assert sorted(ids(run(db, estado_excluir="sin_estado"))) == ["MLA1", "MLA3"]
        assert sorted(ids(run(db, estado_excluir="sin_estado,closed"))) == ["MLA1"]

    def test_a_status_filter_on_its_own_does_not_bring_gone_items_back(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", status="closed")
        seed.add_item(conn, "MLA2", status="closed", gone_at=seed.NOW)
        assert ids(run(db, estado="closed")) == ["MLA1"]

    def test_never_existed_stays_out_even_when_gone_is_asked_for(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", gone_at=seed.NOW, never_existed=True)
        assert ids(run(db, estado="gone")) == []


class TestSearch:
    @pytest.fixture(autouse=True)
    def rows(self, conn) -> None:
        seed.add_product(conn, 70, "7790001234567", "Cámara Hikvision Domo", marca="Hikvision")
        seed.add_product(conn, 72, "KB-HDMI-2M", "Cable HDMI 2m", marca="Kabel")
        seed.add_item(conn, "MLA900100", title="Router Wifi AC1200", seller_sku="ARCHER-C6")
        seed.add_item(conn, "MLA900200", title="Switch 8 puertos", seller_custom_field="SW-08-GIGA")
        seed.add_item(conn, "MLA900300", title="Camara de seguridad")
        seed.add_link(conn, "MLA900300", 70)
        seed.add_item(conn, "MLA900400", title="Cable UTP 100% cobre_x")
        seed.add_item(conn, "MLA900500", title="Soporte universal")
        seed.add_variation(conn, "MLA900500", 1, seller_sku="SOP-VAR-AZUL")
        seed.add_item(conn, "MLA900600", title="Gone router", gone_at=seed.NOW)
        seed.add_item(conn, "MLA900700", title="Alargue")
        seed.add_link(conn, "MLA900700", 72)

    def test_title_is_case_insensitive_substring(self, db) -> None:
        assert ids(run(db, q="wifi ac12")) == ["MLA900100"]
        assert ids(run(db, q="ROUTER")) == ["MLA900100"]

    def test_an_mla_id_is_exact_and_case_insensitive(self, db) -> None:
        assert ids(run(db, q="mla900200")) == ["MLA900200"]
        assert ids(run(db, q="MLA9002")) == []  # a prefix of an id is not an id

    def test_digits_are_the_numeric_part_of_an_mla(self, db) -> None:
        assert ids(run(db, q="900300")) == ["MLA900300"]

    def test_seller_sku_and_seller_custom_field(self, db) -> None:
        assert ids(run(db, q="archer-c")) == ["MLA900100"]
        assert ids(run(db, q="sw-08")) == ["MLA900200"]

    def test_a_variation_sku_finds_its_item_once(self, db) -> None:
        assert ids(run(db, q="sop-var")) == ["MLA900500"]

    def test_the_linked_product_name_and_code(self, db) -> None:
        assert ids(run(db, q="hikvision domo")) == ["MLA900300"]
        assert ids(run(db, q="kb-hdmi")) == ["MLA900700"]  # a fragment of the code is a substring
        assert ids(run(db, q="hdmi 2M")) == ["MLA900700"]

    def test_an_ean_typed_in_full_is_an_exact_key_on_the_product_code(self, db) -> None:
        assert ids(run(db, q="7790001234567")) == ["MLA900300"]
        assert ids(run(db, q="779000123456")) == []  # digits-only is exact, not a prefix

    def test_like_wildcards_are_literal(self, db) -> None:
        assert ids(run(db, q="100%")) == ["MLA900400"]
        assert ids(run(db, q="cobre_x")) == ["MLA900400"]
        assert ids(run(db, q="cobre_y")) == []
        assert ids(run(db, q="%")) == ["MLA900400"]  # only the title that really holds a percent sign

    def test_no_match_is_an_empty_page_with_total_zero(self, db) -> None:
        page = run(db, q="inexistente")
        assert (page.items, page.total) == ([], 0)

    def test_the_search_does_not_bring_gone_items(self, db) -> None:
        assert ids(run(db, q="gone router")) == []
        assert ids(run(db, q="gone router", estado="gone")) == ["MLA900600"]


class TestFilters:
    @pytest.fixture(autouse=True)
    def rows(self, conn) -> None:
        seed.add_product(conn, 70, "A1", "Router", marca="TP-Link", categoria="Redes", subcategoria_id=5)
        seed.add_product(conn, 71, "B1", "Camara", marca="Hikvision", categoria="Video", subcategoria_id=6)
        seed.add_item(conn, "MLA1", status="active", official_store_id=1, family_id=10, listing_type_id="gold_special")
        seed.add_item(conn, "MLA2", status="paused", official_store_id=2, family_id=10, listing_type_id="gold_pro")
        seed.add_item(conn, "MLA3", status="active", official_store_id=2, catalog_listing=True)
        seed.add_item(conn, "MLA4", status="closed", logistic_type="fulfillment")
        seed.add_item(conn, "MLA5", status=None, available_quantity=0, user_product_id="MLAU5")
        seed.add_link(conn, "MLA1", 70)
        seed.add_link(conn, "MLA2", 71, source="manual")
        seed.add_link(conn, "MLA3", None, match_status="conflict")
        seed.add_stock(conn, "MLAU5", full=0, own=3)

    def test_values_of_one_filter_are_ored(self, db) -> None:
        assert sorted(ids(run(db, estado="active,paused"))) == ["MLA1", "MLA2", "MLA3"]
        assert sorted(ids(run(db, tiendas="1,2"))) == ["MLA1", "MLA2", "MLA3"]

    def test_different_filters_are_anded(self, db) -> None:
        assert ids(run(db, tiendas="2", estado="active")) == ["MLA3"]
        assert ids(run(db, tiendas="1,2", estado="active", tipo="catalogo")) == ["MLA3"]

    def test_status_exclude_keeps_the_rows_without_a_status(self, db) -> None:
        assert sorted(ids(run(db, estado_excluir="active,paused"))) == ["MLA4", "MLA5"]

    def test_no_store_matches_the_items_without_one_and_mixes_with_ids(self, db) -> None:
        assert sorted(ids(run(db, tiendas="none"))) == ["MLA4", "MLA5"]
        assert sorted(ids(run(db, tiendas="none,1"))) == ["MLA1", "MLA4", "MLA5"]

    def test_brand_category_and_subcategory_come_from_the_linked_product_ignoring_case(self, db) -> None:
        assert ids(run(db, marcas="tp-link")) == ["MLA1"]
        assert sorted(ids(run(db, marcas="TP-LINK,hikvision"))) == ["MLA1", "MLA2"]
        assert ids(run(db, categorias="video")) == ["MLA2"]
        assert ids(run(db, subcategorias="5")) == ["MLA1"]

    def test_family(self, db) -> None:
        assert sorted(ids(run(db, familia="10"))) == ["MLA1", "MLA2"]

    def test_listing_type_values_are_ored(self, db) -> None:
        assert ids(run(db, tipo="clasica")) == ["MLA1"]
        assert ids(run(db, tipo="premium")) == ["MLA2"]
        assert ids(run(db, tipo="full")) == ["MLA4"]
        assert sorted(ids(run(db, tipo="clasica,catalogo"))) == ["MLA1", "MLA3"]

    def test_link_state(self, db) -> None:
        assert ids(run(db, vinculo="auto")) == ["MLA1"]
        assert ids(run(db, vinculo="manual")) == ["MLA2"]
        assert ids(run(db, vinculo="conflicto")) == ["MLA3"]
        assert sorted(ids(run(db, vinculo="no_evaluado"))) == ["MLA4", "MLA5"]

    def test_stock_filters(self, db) -> None:
        assert ids(run(db, stock="sin_stock")) == ["MLA5"]
        assert ids(run(db, stock="full_sin_stock")) == ["MLA5"]

    def test_full_without_stock_does_not_match_an_item_with_no_stock_row(self, conn, db) -> None:
        seed.add_item(conn, "MLA6", available_quantity=3, user_product_id="MLAU6")  # no stock row: unknown, not zero
        assert "MLA6" not in ids(run(db, stock="full_sin_stock"))

    def test_the_event_filter_matches_items_with_such_an_event_since_the_given_time(self, conn, db) -> None:
        seed.add_event(conn, "MLA1", "price_changed", seed.real_hours_ago(2))
        seed.add_event(conn, "MLA2", "price_changed", seed.real_hours_ago(24 * 10))
        seed.add_event(conn, "MLA3", "status_paused", seed.real_hours_ago(1))
        seed.add_event(conn, "MLA1", "price_changed", seed.real_hours_ago(3))  # two events, still one row
        assert sorted(ids(run(db, evento="price_changed"))) == ["MLA1", "MLA2"]
        assert ids(run(db, evento="price_changed", evento_desde="7d")) == ["MLA1"]
        assert sorted(ids(run(db, evento="price_changed,status_paused", evento_desde="24h"))) == ["MLA1", "MLA3"]


class TestTreeNodeFilters:
    """P7a.T4: the filters a node of the Agrupado tree hands to `/items` for its leaves."""

    @pytest.fixture(autouse=True)
    def rows(self, conn) -> None:
        seed.add_product(conn, 70, "A1", "Router", marca="TP-Link", categoria="Redes", subcategoria_id=5)
        seed.add_product(conn, 71, "B1", "Camara", marca=" tp-link ", categoria="redes", subcategoria_id=6)
        seed.add_product(conn, 72, "C1", "Sin datos")
        seed.add_item(conn, "MLA1", family_id=900, family_name="F")
        seed.add_link(conn, "MLA1", 70)
        seed.add_item(conn, "MLA2")
        seed.add_link(conn, "MLA2", 71)
        seed.add_item(conn, "MLA3")  # no link at all
        seed.add_item(conn, "MLA4")
        seed.add_link(conn, "MLA4", None, match_status="no_product")
        seed.add_item(conn, "MLA5")
        seed.add_link(conn, "MLA5", 72)

    def test_producto_selects_the_publications_of_one_product(self, db) -> None:
        assert ids(run(db, producto="70")) == ["MLA1"]
        assert ids(run(db, producto="71")) == ["MLA2"]
        assert run(db, producto="999").total == 0  # a product that exists nowhere: empty because nothing links to it

    def test_sin_producto_selects_the_publications_with_no_product_whatever_the_reason(self, db) -> None:
        assert sorted(ids(run(db, sin_producto=True))) == ["MLA3", "MLA4"]

    def test_the_none_key_selects_the_rows_with_no_brand_category_or_subcategory(self, db) -> None:
        assert sorted(ids(run(db, marcas="__none__"))) == ["MLA3", "MLA4", "MLA5"]
        assert sorted(ids(run(db, categorias="__none__"))) == ["MLA3", "MLA4", "MLA5"]
        assert sorted(ids(run(db, subcategorias="__none__"))) == ["MLA3", "MLA4", "MLA5"]
        assert sorted(ids(run(db, marcas="__none__,TP-LINK"))) == ["MLA1", "MLA2", "MLA3", "MLA4", "MLA5"]
        assert sorted(ids(run(db, subcategorias="5,__none__"))) == ["MLA1", "MLA3", "MLA4", "MLA5"]

    def test_a_brand_matches_its_trimmed_upper_case_key_like_the_tree_builds_it(self, db) -> None:
        # " tp-link " (padded, lower case) and "TP-Link" are ONE tree node, `TP-LINK`: the filter finds both
        assert sorted(ids(run(db, marcas="TP-LINK"))) == ["MLA1", "MLA2"]
        assert sorted(ids(run(db, categorias="REDES"))) == ["MLA1", "MLA2"]

    def test_a_leaf_row_is_dict_equal_to_the_list_row(self, db) -> None:
        full = {row["item_id"]: row for row in run(db).items}
        leaf = run(db, producto="70", marcas="TP-LINK", categorias="REDES", subcategorias="5", familia="900")
        assert [row for row in leaf.items] == [full["MLA1"]]
        unlinked = run(db, sin_producto=True, marcas="__none__")
        assert {row["item_id"]: row for row in unlinked.items} == {k: full[k] for k in ("MLA3", "MLA4")}


class TestProductManagerFilter:
    @pytest.fixture(autouse=True)
    def rows(self, conn) -> None:
        conn.execute(
            text("CREATE TABLE marcas_pm (id serial PRIMARY KEY, marca text, categoria text, usuario_id integer)")
        )
        conn.execute(text("INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES ('tp-link', 'redes', 7)"))
        seed.add_product(conn, 70, "A1", "Router", marca="TP-Link", categoria="Redes")
        seed.add_product(conn, 71, "B1", "Camara", marca="TP-Link", categoria="Video")
        seed.add_item(conn, "MLA1")
        seed.add_item(conn, "MLA2")
        seed.add_item(conn, "MLA3")
        seed.add_link(conn, "MLA1", 70)
        seed.add_link(conn, "MLA2", 71)

    def test_a_pm_filters_by_the_marca_and_categoria_pairs_it_owns(self, db) -> None:
        assert ids(run(db, pms="7")) == ["MLA1"]

    def test_an_assignment_row_with_a_null_marca_or_categoria_is_ignored(self, conn, db) -> None:
        conn.execute(text("INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES (NULL, 'redes', 7)"))
        conn.execute(text("INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES ('tp-link', NULL, 7)"))
        assert ids(run(db, pms="7")) == ["MLA1"]  # the one complete pair still applies; the broken rows are skipped

    def test_a_padded_brand_or_category_is_the_same_pair_as_the_tree_node_it_sits_in(self, conn, db) -> None:
        # " tp-link " is the `TP-LINK` node of the tree (trimmed key), so the PM who owns TP-LINK / REDES owns it too
        seed.add_product(conn, 72, "C1", "Switch", marca=" tp-link ", categoria=" Redes")
        seed.add_item(conn, "MLA4")
        seed.add_link(conn, "MLA4", 72)
        assert sorted(ids(run(db, pms="7"))) == ["MLA1", "MLA4"]
        conn.execute(text("INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES (' Tenda ', 'redes ', 8)"))
        seed.add_product(conn, 73, "D1", "Antena", marca="TENDA", categoria="REDES")
        seed.add_item(conn, "MLA5")
        seed.add_link(conn, "MLA5", 73)
        assert ids(run(db, pms="8")) == ["MLA5"]  # a padded assignment row matches the trimmed key as well

    def test_a_name_that_python_and_postgres_upper_case_differently_still_matches_its_pair(self, conn, db) -> None:
        conn.execute(text("INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES ('Maßstab', 'Straße', 9)"))
        seed.add_product(conn, 74, "E1", "Masa", marca="Maßstab", categoria="Straße")
        seed.add_item(conn, "MLA6")
        seed.add_link(conn, "MLA6", 74)
        assert ids(run(db, pms="9")) == ["MLA6"]

    def test_a_pm_without_pairs_matches_nothing_never_everything(self, db) -> None:
        page = run(db, pms="99")
        assert (ids(page), page.total) == ([], 0)


class TestInvalidFilters:
    def test_the_event_filter_with_the_events_flag_off_is_refused(self, db) -> None:
        with pytest.raises(FilterError) as caught:
            listing.list_items(
                db, parse_filter(evento="price_changed"), listing.parse_sort(None, None), 50, 0, events=False
            )
        assert caught.value.field == "evento"


class TestSorting:
    def test_the_default_is_recent_activity_newest_first_with_events_off(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", last_trigger_received_at=seed.hours_ago(5))
        seed.add_item(conn, "MLA2", last_trigger_received_at=seed.hours_ago(1))
        seed.add_item(conn, "MLA3", last_trigger_received_at=seed.hours_ago(3))
        page = run(db, events=False)
        assert ids(page) == ["MLA2", "MLA3", "MLA1"]
        assert all("last_event" not in row for row in page.items)

    @pytest.mark.parametrize(
        "direction, expected", [("desc", ["MLA2", "MLA1", "MLA3"]), ("asc", ["MLA1", "MLA2", "MLA3"])]
    )
    def test_an_item_without_activity_is_last_in_either_direction(self, conn, db, direction, expected) -> None:
        seed.add_item(conn, "MLA1", last_trigger_received_at=seed.hours_ago(5))
        seed.add_item(conn, "MLA2", last_trigger_received_at=seed.hours_ago(1))
        seed.add_item(conn, "MLA3")
        assert ids(run(db, orden="actividad", direction=direction)) == expected

    def test_price_orders_by_the_ml_price_sale_price_first_nulls_last(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", price=500)
        seed.add_item(conn, "MLA2", price=1000)
        seed.add_sale_price(conn, "MLA2", 300)  # the sale price wins: 300, not 1000
        seed.add_item(conn, "MLA3", price=700)
        seed.add_item(conn, "MLA4")
        assert ids(run(db, orden="precio", direction="asc")) == ["MLA2", "MLA1", "MLA3", "MLA4"]
        assert ids(run(db, orden="precio", direction="desc")) == ["MLA3", "MLA1", "MLA2", "MLA4"]

    def test_title_ignores_case_and_puts_missing_titles_last(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", title="banana")
        seed.add_item(conn, "MLA2", title="Apple")
        seed.add_item(conn, "MLA3", title="cherry")
        seed.add_item(conn, "MLA4")
        assert ids(run(db, orden="titulo", direction="asc")) == ["MLA2", "MLA1", "MLA3", "MLA4"]
        assert ids(run(db, orden="titulo", direction="desc")) == ["MLA3", "MLA1", "MLA2", "MLA4"]

    def test_full_stock_puts_unknown_last_and_a_real_zero_before_it(self, conn, db) -> None:
        for item_id, up, full in (("MLA1", "MLAU1", 5), ("MLA2", "MLAU2", 0), ("MLA3", "MLAU3", 9)):
            seed.add_item(conn, item_id, user_product_id=up)
            seed.add_stock(conn, up, full=full, own=0)
        seed.add_item(conn, "MLA4", user_product_id="MLAU4")  # no stock row: unknown
        assert ids(run(db, orden="stock_full", direction="desc")) == ["MLA3", "MLA1", "MLA2", "MLA4"]
        assert ids(run(db, orden="stock_full", direction="asc")) == ["MLA2", "MLA1", "MLA3", "MLA4"]

    def test_updated_orders_by_the_ml_last_update_newest_first_by_default(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", ml_last_updated=seed.hours_ago(9))
        seed.add_item(conn, "MLA2", ml_last_updated=seed.hours_ago(2))
        seed.add_item(conn, "MLA3")
        assert ids(run(db, orden="actualizado")) == ["MLA2", "MLA1", "MLA3"]
        assert ids(run(db, orden="actualizado", direction="asc")) == ["MLA1", "MLA2", "MLA3"]

    def test_text_and_price_sorts_default_to_ascending(self, conn, db) -> None:
        seed.add_item(conn, "MLA1", title="b", price=2)
        seed.add_item(conn, "MLA2", title="a", price=9)
        assert ids(run(db, orden="titulo")) == ["MLA2", "MLA1"]
        assert ids(run(db, orden="precio")) == ["MLA1", "MLA2"]

    @pytest.mark.parametrize("params", [{"orden": "nope"}, {"dir": "sideways"}])
    def test_an_unknown_sort_or_direction_is_refused(self, params) -> None:
        with pytest.raises(FilterError):
            listing.parse_sort(params.get("orden"), params.get("dir"))

    def test_the_markup_sort_puts_the_worst_first_by_default(self) -> None:
        assert listing.parse_sort("markup", None) == listing.Sort("markup", descending=False)
        assert listing.parse_sort("markup", "desc") == listing.Sort("markup", descending=True)

    def test_the_markup_sort_without_the_margin_permission_is_refused_by_the_service_too(self, conn, db) -> None:
        seed.add_item(conn, "MLA1")
        with pytest.raises(FilterError) as refused:
            run(db, orden="markup")
        assert refused.value.field == "orden"


class TestPaging:
    @pytest.fixture()
    def many(self, conn) -> None:
        for n in range(120):  # one shared activity time: the tie is broken by item_id only
            seed.add_item(conn, f"MLA{n:04d}", title="igual", last_trigger_received_at=seed.NOW)

    @pytest.mark.parametrize("orden", ["actividad", "titulo", "precio", "stock_full", "actualizado"])
    def test_equal_keys_page_without_repeats_or_skips(self, many, db, orden) -> None:
        pages = [ids(run(db, orden=orden, limit=50, offset=offset)) for offset in (0, 50, 100)]
        assert [len(p) for p in pages] == [50, 50, 20]
        flat = [item_id for page in pages for item_id in page]
        assert flat == sorted(flat) and len(set(flat)) == 120

    def test_the_last_page_holds_the_rest_and_the_total_is_the_filtered_set(self, many, db) -> None:
        page = run(db, limit=50, offset=100)
        assert len(page.items) == 20 and page.total == 120

    def test_a_page_beyond_the_end_is_empty_with_the_total_intact(self, many, db) -> None:
        page = run(db, limit=50, offset=99 * 50)
        assert page.items == [] and page.total == 120

    def test_the_total_follows_the_filter_not_the_page(self, conn, many, db) -> None:
        seed.add_item(conn, "MLAX", title="distinto")
        page = run(db, q="distinto", limit=1)
        assert ids(page) == ["MLAX"] and page.total == 1


class TestFacets:
    @pytest.fixture(autouse=True)
    def rows(self, conn) -> None:
        seed.add_product(conn, 70, "A1", "Router", marca="TP-Link")
        seed.add_product(conn, 71, "B1", "Camara", marca="Hikvision")
        seed.add_item(conn, "MLA1", status="active", official_store_id=1, listing_type_id="gold_special")
        seed.add_item(conn, "MLA2", status="active", official_store_id=2, listing_type_id="gold_pro")
        seed.add_item(conn, "MLA3", status="paused", official_store_id=2, logistic_type="fulfillment")
        seed.add_item(conn, "MLA4", status="closed", catalog_listing=True, available_quantity=0)
        seed.add_item(conn, "MLA5", status="active", official_store_id=1, user_product_id="MLAU5")
        seed.add_item(conn, "MLA6", status="closed", gone_at=seed.NOW)  # gone: only the status facet offers it
        seed.add_link(conn, "MLA1", 70)
        seed.add_link(conn, "MLA2", 71, source="manual")
        seed.add_link(conn, "MLA3", None, match_status="conflict")
        seed.add_stock(conn, "MLAU5", full=0, own=1)

    def test_a_padded_brand_is_the_same_facet_value_as_its_trimmed_spelling(self, conn, db) -> None:
        seed.add_product(conn, 72, "C1", "Switch", marca=" tp-link ")
        seed.add_item(conn, "MLA7", status="active")
        seed.add_link(conn, "MLA7", 72)
        brands = listing.facets(db, parse_filter())["marcas"]
        assert brands == {"TP-LINK": 2, "HIKVISION": 1}  # one value, and selecting it lists both publications
        assert sorted(ids(run(db, marcas="TP-LINK"))) == ["MLA1", "MLA7"]
        assert brands["TP-LINK"] == run(db, marcas="TP-LINK").total

    def test_a_brand_with_a_comma_is_offered_under_a_key_the_filter_takes_back(self, conn, db) -> None:
        seed.add_product(conn, 74, "E1", "Parlante", marca="Audio, Video Inc")
        seed.add_item(conn, "MLA9", status="active")
        seed.add_link(conn, "MLA9", 74)
        brands = listing.facets(db, parse_filter())["marcas"]
        key = next(k for k in brands if "AUDIO" in k)
        assert "," not in key and brands[key] == 1
        assert ids(run(db, marcas=key)) == ["MLA9"]

    def test_a_product_with_a_blank_brand_is_not_offered_as_a_brand(self, conn, db) -> None:
        seed.add_product(conn, 73, "D1", "Sin marca", marca="   ")
        seed.add_item(conn, "MLA8", status="active")
        seed.add_link(conn, "MLA8", 73)
        assert listing.facets(db, parse_filter())["marcas"] == {"TP-LINK": 1, "HIKVISION": 1}

    def test_every_axis_counts_the_whole_set_when_nothing_is_selected(self, db) -> None:
        facets = listing.facets(db, parse_filter())
        assert facets == {
            "status": {"active": 3, "paused": 1, "closed": 1, "gone": 1},
            "stores": {"1": 2, "2": 2, "none": 1},
            "marcas": {"TP-LINK": 1, "HIKVISION": 1},
            "listing": {"clasica": 1, "premium": 1, "catalogo": 1, "full": 1},
            "link": {"auto": 1, "manual": 1, "conflicto": 1, "no_evaluado": 2},
            "stock": {"sin_stock": 1, "full_sin_stock": 1},
        }

    def test_an_axis_ignores_its_own_selection_and_obeys_the_others(self, db) -> None:
        facets = listing.facets(db, parse_filter(estado="active", tiendas="2"))
        # the status facet ignores `estado` but keeps `tiendas=2`; the stores facet ignores `tiendas` but keeps `estado`
        assert facets["status"] == {"active": 1, "paused": 1}
        assert facets["stores"] == {"1": 2, "2": 1}
        assert facets["link"] == {"manual": 1}

    def test_every_status_the_facet_offers_can_be_selected_and_gives_its_count(self, conn, db) -> None:
        seed.add_item(conn, "MLA7", status=None)  # the facet calls it `sin_estado`
        offered = listing.facets(db, parse_filter())["status"]
        assert set(offered) == {"active", "paused", "closed", "gone", "sin_estado"}
        for value, count in offered.items():
            assert run(db, estado=value).total == count, value

    def test_the_status_facet_offers_gone_even_while_gone_is_selected(self, db) -> None:
        # selecting `gone` must not hide the other statuses' counts, nor make the gone count vanish
        facets = listing.facets(db, parse_filter(estado="gone"))
        assert facets["status"] == {"active": 3, "paused": 1, "closed": 1, "gone": 1}
        assert facets["stores"] == {"none": 1}  # the other axes obey it: the one gone item has no store

    def test_the_store_facet_counts_only_what_the_status_filter_lets_through(self, db) -> None:
        assert listing.facets(db, parse_filter(estado="paused"))["stores"] == {"2": 1}

    def test_the_search_applies_to_every_axis(self, db) -> None:
        facets = listing.facets(db, parse_filter(q="MLA1"))
        assert facets["status"] == {"active": 1}
        assert facets["stores"] == {"1": 1}
        assert facets["link"] == {"auto": 1}

    def test_the_brand_axis_ignores_a_brand_selection(self, db) -> None:
        assert listing.facets(db, parse_filter(marcas="tp-link"))["marcas"] == {"TP-LINK": 1, "HIKVISION": 1}

    def test_an_empty_store_answers_empty_axes_without_error(self, conn, db) -> None:
        conn.execute(text("DELETE FROM ml_items"))
        assert listing.facets(db, parse_filter()) == {
            "status": {},
            "stores": {},
            "marcas": {},
            "listing": {"clasica": 0, "premium": 0, "catalogo": 0, "full": 0},
            "link": {},
            "stock": {"sin_stock": 0, "full_sin_stock": 0},
        }

    def test_one_statement_per_axis_whatever_the_data(self, db) -> None:
        from sqlalchemy import event

        statements: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            statements.append(statement)

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            listing.facets(db, parse_filter())
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert len(statements) == len(listing.FACET_AXES) == 6
