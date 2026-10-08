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


def run(db: Session, *, limit: int = 50, offset: int = 0, events: bool = True, orden=None, dir=None, **params):
    return listing.list_items(db, parse_filter(**params), listing.parse_sort(orden, dir), limit, offset, events=events)


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
        seed.add_event(conn, "MLA1", "price_changed", seed.hours_ago(2))
        seed.add_event(conn, "MLA2", "price_changed", seed.hours_ago(24 * 10))
        seed.add_event(conn, "MLA3", "status_paused", seed.hours_ago(1))
        seed.add_event(conn, "MLA1", "price_changed", seed.hours_ago(3))  # two events, still one row
        assert sorted(ids(run(db, evento="price_changed"))) == ["MLA1", "MLA2"]
        assert ids(run(db, evento="price_changed", evento_desde="7d")) == ["MLA1"]
        assert sorted(ids(run(db, evento="price_changed,status_paused", evento_desde="24h"))) == ["MLA1", "MLA3"]


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
