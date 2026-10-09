"""P8a.T2: `GET /api/ml-publications/view/items/{item_id}`, the Resumen of the detail panel.

Same harness as the variations and list tests (permissions in the SQLite test database, the store in a throwaway
Postgres schema built from the real migrations). The pricing context and the real shipping batch are stubbed with the
hand-built ones of `test_unit_markup.py`: this file pins the HTTP contract, the gating, the honest states and the
statement count, not the maths (P2: `test_unit_breakdown.py`).
"""

# ruff: noqa: F811 -- the fixtures are imported from the list's test modules and used by name

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import event, text

from app.models.ml_publications import MlItem
from app.routers import ml_publications_admin, ml_publications_view
from app.services.ml_publications import settings_store
from app.services.ml_publications.view import detail
from app.services.ml_publications.view.markup import unit_breakdown, unit_markup
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import seed_rows
from tests.routers.test_ml_publications_view_markup import (  # noqa: F401
    COST,
    analyst,
    pg,
    pricing,
    reader,
    view_pg,
)
from tests.services.ml_publications.conftest import bulk_item, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_unit_markup import make_ctx, make_inputs

pytestmark = pytest.mark.postgres

BASE = "/api/ml-publications/view/items"
GESTIONAR = "ml_ops.gestionar"
GANANCIA = "ml_metricas.ver_ganancia"
CAPTURED = bulk_item("MLA935110613")  # a real item body, from the first /items/bulk capture


def url(item_id: str) -> str:
    return f"{BASE}/{item_id}"


def detail_of(client, headers, item_id: str = "MLA10", **params):
    return client.get(url(item_id), headers=headers, params=params)


def body_of(client, headers, item_id: str = "MLA10", **params) -> dict:
    response = detail_of(client, headers, item_id, **params)
    assert response.status_code == 200, response.text
    return response.json()


def priced(conn, item_id: str, **columns) -> None:
    """A publication on the 9x list with a sale price: the markup of product `n` is `worst_of(n)`."""
    seed.add_item(conn, item_id, listing_type_id="gold_pro", tags=["9x_campaign"], price=90000, **columns)
    seed.add_sale_price(conn, item_id, 100000)


def stored_markup(product: int) -> float:
    """The unit markup of `product` priced with the cost fields `fill` stores (VAT 10.5, ERP shipping 120)."""
    inputs = make_inputs(producto_item_id=product, costo=COST[product], iva=10.5, envio=120.0)
    value = unit_markup(make_ctx(), inputs, {}).value
    assert value is not None
    return value


def json_param(value) -> str:
    return json.dumps(value)


def fill(conn) -> None:
    """MLA10: a Full publication with a family, a store, three live variations (one gone), links of every kind and
    stock in both places. MLA11: one product linked at item level, no variations. MLA12: nothing linked."""
    conn.execute(text("INSERT INTO ml_tiendas_oficiales (store_id, nombre) VALUES (2645, 'TP-Link')"))
    conn.execute(
        text("INSERT INTO subcategorias_grupos (subcat_id, grupo_id, nombre_subcategoria) VALUES (3845, 1, 'Camaras')")
    )
    for item_id, cost in COST.items():
        seed.add_product(
            conn,
            item_id,
            f"C{item_id}",
            f"Producto {item_id}",
            marca=f"M{item_id}",
            categoria="SEGURIDAD",
            subcategoria_id=3845,
        )
        seed.add_cost(conn, item_id, cost, iva=10.5, envio=120.0)
    seed.add_pricing(conn, 70, precio_lista_ml=111.5, precio_3_cuotas=122.0, precio_12_cuotas=199.0)
    priced(
        conn,
        "MLA10",
        title="Camara",
        status="active",
        logistic_type="fulfillment",
        user_product_id="MLAU10",
        family_id=555,
        family_name="Camaras",
        official_store_id=2645,
        brand="Hikvision",
        seller_id=413658225,
        category_id="MLA1000",
        domain_id="MLA-CAMERAS",
        condition="new",
        buying_mode="buy_it_now",
        currency_id="ARS",
        available_quantity=30,
        sold_quantity=7,
        initial_quantity=50,
        sub_status=["out_of_stock"],
        health=0.8,
        free_shipping=True,
        shipping_mode="me2",
        date_created=seed.hours_ago(500),
        ml_last_updated=seed.hours_ago(5),
        fetched_at=seed.hours_ago(1),
        last_checked_at=seed.hours_ago(0.5),
        last_trigger_received_at=seed.hours_ago(2),
        http_status=200,
    )
    seed.add_link(conn, "MLA10", 72)
    seed.add_variation(conn, "MLA10", 11, seller_sku="SKU-A", available_quantity=10)
    seed.add_variation(conn, "MLA10", 12, seller_custom_field="CUSTOM-B", available_quantity=5)
    seed.add_variation(conn, "MLA10", 13, available_quantity=15)
    seed.add_variation(conn, "MLA10", 14, gone_at=seed.NOW)
    seed.add_link(conn, "MLA10", 70, variation_id=11)
    seed.add_link(conn, "MLA10", 71, variation_id=12, source="manual")
    seed.add_link(conn, "MLA10", None, variation_id=13, match_status="unmatched")
    seed.add_stock_locations(
        conn,
        "MLAU10",
        [{"type": "meli_facility", "quantity": 20}, {"type": "selling_address", "quantity": 3}],
        ml_last_updated=seed.hours_ago(3),
    )
    conn.execute(
        text(
            "UPDATE ml_user_product_stock SET full_quantity = 20, own_quantity = 3, total_quantity = 23 "
            "WHERE user_product_id = 'MLAU10'"
        )
    )
    seed.add_replenishment(
        conn,
        "MLAU10",
        partial=False,
        period="last_30_days",
        units_30d=42,
        gmv_30d=1234567.5,
        currency_id="ARS",
        units_7d=9,
        units_14d=18,
        units_21d=30,
        days_out_of_stock_21d=2,
        total_stock=184,
        shipping_urgency="IN_TWO_WEEKS",
        minimum_distributable_stock=12,
        fetched_at=seed.hours_ago(6),
        last_checked_at=seed.hours_ago(4),
    )
    seed.add_state(
        conn,
        "ml_item_descriptions",
        "item_id",
        "MLA10",
        http_status=200,
        fetched_at=seed.hours_ago(9),
        last_checked_at=seed.hours_ago(8),
    )
    seed.add_state(conn, "ml_item_visits", "item_id", "MLA10", http_status=500, last_checked_at=seed.hours_ago(7))
    seed.add_state(conn, "ml_item_moderations", "item_id", "MLA10", http_status=404, last_checked_at=seed.hours_ago(7))
    seed.add_state(
        conn, "ml_user_product_families", "family_id", 555, http_status=200, last_checked_at=seed.hours_ago(7)
    )
    priced(conn, "MLA11", title="Domo", user_product_id="MLAU11", http_status=200)
    seed.add_link(conn, "MLA11", 70)
    priced(conn, "MLA12", title="Sin vinculo")


@pytest.fixture()
def rows(pg):
    seed_rows(pg, fill)


@pytest.fixture()
def manager(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, "ml_ops.ver", GESTIONAR)
    return admin_auth_headers


@pytest.fixture()
def full_analyst(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, "ml_ops.ver", GANANCIA, GESTIONAR)
    return admin_auth_headers


class TestErrors:
    def test_unknown_item_is_404(self, client, rows, reader, pricing) -> None:
        response = detail_of(client, reader, "MLA404")
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"

    def test_an_id_that_ml_says_never_existed_is_404_like_in_the_list(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, lambda conn: seed.add_item(conn, "MLA77", never_existed=True))
        assert detail_of(client, reader, "MLA77").status_code == 404

    @pytest.mark.parametrize("item_id", ["mla10", "MLA", "10", "MLA1x"])
    def test_a_malformed_id_is_422(self, client, rows, reader, pricing, item_id) -> None:
        assert detail_of(client, reader, item_id).status_code == 422

    def test_without_ml_ops_ver_it_is_403(self, client, rows, auth_headers, pricing) -> None:
        response = detail_of(client, auth_headers)
        assert response.status_code == 403 and "ml_ops.ver" in response.json()["error"]["message"]

    def test_authentication_is_required(self, client, rows, pricing) -> None:
        assert client.get(url("MLA10")).status_code in (401, 403)

    def test_the_permission_codes_are_the_catalog_ones(self) -> None:
        assert ml_publications_view.PERMISO_GESTIONAR == ml_publications_admin.PERMISO_GESTIONAR == GESTIONAR

    def test_the_variations_are_not_repeated_here(self, client, rows, reader, pricing) -> None:
        assert "variations" not in body_of(client, reader)  # they stay on `/items/{id}/variations` (P6c)


class TestRow:
    def test_the_row_is_the_list_row(self, client, rows, reader, pricing) -> None:
        listed = client.get(BASE, headers=reader, params={"q": "MLA10"}).json()["items"]
        assert [r["item_id"] for r in listed] == ["MLA10"]
        assert body_of(client, reader)["row"] == listed[0]

    def test_with_margin_the_row_carries_the_same_markup_block(self, client, rows, analyst, pricing) -> None:
        listed = client.get(BASE, headers=analyst, params={"q": "MLA10"}).json()["items"][0]
        row = body_of(client, analyst)["row"]
        assert row == listed and row["markup"]["worst"] == round(stored_markup(71), 2)

    def test_a_gone_publication_has_its_row_too(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, lambda conn: seed.add_item(conn, "MLA90", title="Viejo", status="closed", gone_at=seed.NOW))
        row = body_of(client, reader, "MLA90")["row"]
        listed = client.get(BASE, headers=reader, params={"estado": "gone"}).json()["items"][0]
        assert row == listed and row["gone"] is True

    def test_the_last_event_follows_the_flag_like_the_list(self, client, rows, reader, pricing, pg) -> None:
        assert "last_event" not in body_of(client, reader)["row"]
        settings_store.set_setting("events.enabled", True, "test")
        with pg.begin() as conn:
            seed.add_event(conn, "MLA10", "price_changed", seed.hours_ago(1))
        listed = client.get(BASE, headers=reader, params={"q": "MLA10"}).json()["items"][0]
        row = body_of(client, reader)["row"]
        assert row == listed and row["last_event"]["event_type"] == "price_changed"

    def test_the_store_label_and_variation_count_come_with_it(self, client, rows, reader, pricing) -> None:
        row = body_of(client, reader)["row"]
        assert row["store_label"] == "TP-Link" and row["variations_count"] == 3  # the gone one is not counted


class TestItemFields:
    def test_every_ml_items_column_but_raw_and_its_hash(self, client, rows, reader, pricing) -> None:
        item = body_of(client, reader)["item"]
        columns = {column.key for column in MlItem.__table__.columns}
        assert set(item) == columns - {"raw", "raw_hash"}

    def test_the_values_are_the_stored_ones(self, client, rows, reader, pricing) -> None:
        item = body_of(client, reader)["item"]
        assert (item["seller_id"], item["initial_quantity"], item["sold_quantity"]) == (413658225, 50, 7)
        assert (item["buying_mode"], item["currency_id"], item["shipping_mode"]) == ("buy_it_now", "ARS", "me2")
        assert (item["category_id"], item["domain_id"], item["free_shipping"]) == ("MLA1000", "MLA-CAMERAS", True)
        assert item["price"] == 90000 and item["http_status"] == 200

    def test_the_design_fields_stay_at_the_top_level(self, client, rows, reader, pricing) -> None:
        body = body_of(client, reader)
        assert body["sub_status"] == ["out_of_stock"] and body["tags"] == ["9x_campaign"]
        assert body["health"] == 0.8 and body["condition"] == "new"
        for name in ("date_created", "ml_last_updated", "fetched_at"):
            assert body[name] is not None
        assert body["fetched_at"] == body["item"]["fetched_at"]

    def test_the_captured_extras_are_the_whitelisted_ones(self, client, pg, reader, pricing) -> None:
        def captured(conn) -> None:
            priced(conn, "MLA50", title="Capturado")
            conn.execute(
                text("UPDATE ml_items SET raw = CAST(:raw AS jsonb) WHERE item_id = 'MLA50'"),
                {"raw": json_param(CAPTURED)},
            )

        seed_rows(pg, captured)
        extra = body_of(client, reader, "MLA50")["extra"]
        assert extra == detail.extra_fields(CAPTURED)
        assert set(extra) == set(detail.EXTRA_FIELDS)
        assert extra["warranty"] == CAPTURED["warranty"]
        assert extra["shipping"]["mode"] == CAPTURED["shipping"]["mode"]

    def test_without_a_raw_there_are_no_extras(self, client, rows, reader, pricing) -> None:
        extra = body_of(client, reader)["extra"]
        assert set(extra) == set(detail.EXTRA_FIELDS) and all(value is None for value in extra.values())


class TestStock:
    def test_the_locations_of_the_stock_body(self, client, rows, reader, pricing) -> None:
        body = body_of(client, reader)
        assert body["stock_locations"] == [
            {"type": "meli_facility", "quantity": 20},
            {"type": "selling_address", "quantity": 3},
        ]
        assert body["stock_as_of"] is not None and body["row"]["stock"]["full"] == 20

    def test_no_stock_row_means_unknown_not_empty(self, client, rows, reader, pricing) -> None:
        body = body_of(client, reader, "MLA11")
        assert body["stock_locations"] is None and body["stock_as_of"] is None

    @pytest.mark.parametrize("locations", [None, "x", {"type": "meli_facility"}])
    def test_a_body_without_a_list_of_locations_is_unknown(self, client, pg, reader, pricing, locations) -> None:
        def odd(conn) -> None:
            priced(conn, "MLA51", user_product_id="MLAU51")
            seed.add_stock_locations(conn, "MLAU51", locations)

        seed_rows(pg, odd)
        assert body_of(client, reader, "MLA51")["stock_locations"] is None

    def test_malformed_entries_are_skipped_not_invented(self, client, pg, reader, pricing) -> None:
        def odd(conn) -> None:
            priced(conn, "MLA52", user_product_id="MLAU52")
            seed.add_stock_locations(conn, "MLAU52", [{"type": "meli_facility", "quantity": 4}, "x", {"quantity": 1}])

        seed_rows(pg, odd)
        assert body_of(client, reader, "MLA52")["stock_locations"] == [{"type": "meli_facility", "quantity": 4}]


class TestReplenishment:
    def states(self, conn) -> None:
        for number, up in ((21, "MLAU21"), (22, "MLAU22"), (23, "MLAU23"), (24, "MLAU24")):
            priced(conn, f"MLA{number}", logistic_type="fulfillment", user_product_id=up)
        priced(conn, "MLA25", logistic_type="cross_docking", user_product_id="MLAU25")
        priced(conn, "MLA26", logistic_type="fulfillment")  # Full without a user product: nothing to fetch
        priced(conn, "MLA27")  # no logistic type at all
        seed.add_replenishment(conn, "MLAU21", partial=True, content_missing="sales", units_30d=5)
        seed.add_replenishment(conn, "MLAU22", http_status=404, never_existed=True)
        seed.add_replenishment(conn, "MLAU23", http_status=500, last_error="boom")
        seed.add_replenishment(conn, "MLAU25", units_30d=99)  # a row exists, but the publication is not Full

    def test_ok_has_every_figure(self, client, rows, reader, pricing) -> None:
        got = body_of(client, reader)["replenishment"]
        assert got.pop("fetched_at") is not None
        assert got == {
            "status": "ok",
            "content_missing": None,
            "period": "last_30_days",
            "units_30d": 42,
            "gmv_30d": 1234567.5,
            "currency": "ARS",
            "units_7d": 9,
            "units_14d": 18,
            "units_21d": 30,
            "days_out_of_stock_21d": 2,
            "shipping_urgency": "IN_TWO_WEEKS",
            "total_stock": 184,
            "minimum_distributable_stock": 12,
            "history_through": None,
        }

    def test_partial_keeps_what_is_missing(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, self.states)
        got = body_of(client, reader, "MLA21")["replenishment"]
        assert got["status"] == "partial" and got["content_missing"] == "sales" and got["units_30d"] == 5

    def test_not_found_and_error_are_told_apart(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, self.states)
        assert body_of(client, reader, "MLA22")["replenishment"]["status"] == "not_found"
        assert body_of(client, reader, "MLA23")["replenishment"]["status"] == "error"

    def test_a_full_publication_never_fetched_says_so(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, self.states)
        for item_id in ("MLA24", "MLA26"):
            got = body_of(client, reader, item_id)["replenishment"]
            assert got["status"] == "never_fetched"
            assert {v for k, v in got.items() if k != "status"} == {None}

    def test_it_is_null_when_the_publication_is_not_full(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, self.states)
        body = body_of(client, reader, "MLA25")
        assert body["replenishment"] is None and body["row"]["is_full"] is False
        assert body_of(client, reader, "MLA27")["replenishment"] is None


class TestLinksAndProduct:
    def test_every_unit_has_its_link(self, client, rows, reader, pricing) -> None:
        links = {link["variation_id"]: link for link in body_of(client, reader)["links"]}
        assert sorted(links) == [0, 11, 12, 13]  # item level first, then each variation, by id
        assert [link["variation_id"] for link in body_of(client, reader)["links"]] == [0, 11, 12, 13]
        assert links[0]["state"] == "auto" and links[0]["producto_item_id"] == 72 and links[0]["codigo"] == "C72"
        assert links[11]["state"] == "auto" and links[11]["descripcion"] == "Producto 70"
        assert links[12]["state"] == "manual" and links[12]["source"] == "manual" and links[12]["marca"] == "M71"
        assert links[13]["state"] == "sin_producto" and links[13]["producto_item_id"] is None
        assert links[13]["codigo"] is None

    def test_no_links_at_all_is_an_empty_list(self, client, rows, reader, pricing) -> None:
        assert body_of(client, reader, "MLA12")["links"] == []

    def test_a_link_to_a_vanished_product_keeps_the_id_and_shows_no_data(self, client, pg, reader, pricing) -> None:
        def dangling(conn) -> None:
            priced(conn, "MLA53")
            seed.add_link(conn, "MLA53", 999)

        seed_rows(pg, dangling)
        body = body_of(client, reader, "MLA53")
        assert body["links"][0]["producto_item_id"] == 999 and body["links"][0]["codigo"] is None
        assert body["product"] is None

    def test_the_product_of_the_item_level_link(self, client, rows, reader, pricing) -> None:
        product = body_of(client, reader, "MLA11")["product"]
        assert product["item_id"] == 70 and product["codigo"] == "C70" and product["descripcion"] == "Producto 70"
        assert product["marca"] == "M70" and product["categoria"] == "SEGURIDAD"
        assert product["subcategoria_id"] == 3845 and product["subcategoria"] == "Camaras"
        assert product["precios_lista"] == {"4": 111.5, "17": 122.0, "14": None, "13": None, "23": 199.0}

    def test_a_product_without_pricing_row_has_empty_lists(self, client, rows, reader, pricing) -> None:
        assert set(body_of(client, reader)["product"]["precios_lista"].values()) == {None}  # MLA10 -> product 72

    def test_no_product_without_an_item_level_link(self, client, rows, reader, pricing) -> None:
        assert body_of(client, reader, "MLA12")["product"] is None


class TestMargin:
    COST_KEYS = {"costo", "moneda_costo", "iva"}

    def test_without_ver_ganancia_there_is_no_cost_and_no_breakdown_at_all(self, client, rows, reader, pricing) -> None:
        body = body_of(client, reader, "MLA11")
        assert "markup_breakdown" not in body and "markup" not in body["row"]
        assert self.COST_KEYS.isdisjoint(body["product"])
        assert "costo" not in json.dumps(body)  # no cost field anywhere, whatever its place
        assert pricing == []  # nothing was priced, not even the shipping batch

    def test_with_ver_ganancia_the_product_shows_its_cost(self, client, rows, analyst, pricing) -> None:
        product = body_of(client, analyst, "MLA11")["product"]
        assert (product["costo"], product["moneda_costo"], product["iva"]) == (COST[70], "ARS", 10.5)

    def test_the_breakdown_is_the_unit_markup_of_the_stored_inputs(self, client, rows, analyst, pricing) -> None:
        got = body_of(client, analyst, "MLA11")["markup_breakdown"]
        expected = unit_breakdown(
            make_ctx(), make_inputs(producto_item_id=70, costo=COST[70], iva=10.5, envio=120.0), {}
        )
        assert got == {
            "variation_id": None,
            "price": 100000.0,
            "price_source": "sale_price",
            "pricelist_id": 13,
            "installments": 9,
            "comision_pct": round(expected.comision_pct, 2),
            "comision_total": round(expected.comision_total, 2),
            "costo_envio": 120.0,
            "envio_source": "erp",
            "limpio": round(expected.limpio, 2),
            "costo_ars": COST[70],
            "markup": round(expected.markup, 2),
        }

    def test_with_variations_it_explains_the_worst_one(self, client, rows, analyst, pricing) -> None:
        got = body_of(client, analyst)["markup_breakdown"]
        assert got["variation_id"] == 12 and got["costo_ars"] == COST[71]  # product 71 is the worst of the three
        assert got["markup"] == round(stored_markup(71), 2)

    def test_the_breakdown_markup_is_the_rows_worst(self, client, rows, analyst, pricing) -> None:
        body = body_of(client, analyst)
        assert body["markup_breakdown"]["markup"] == body["row"]["markup"]["worst"]

    def test_what_cannot_be_priced_has_a_null_breakdown_and_the_row_says_why(
        self, client, rows, analyst, pricing
    ) -> None:
        body = body_of(client, analyst, "MLA12")
        assert body["markup_breakdown"] is None and body["row"]["markup"]["reason"] == "sin_vinculo"

    def test_one_shipping_batch_for_the_publication(self, client, rows, analyst, pricing) -> None:
        body_of(client, analyst)
        assert pricing == [[70, 71, 72]]


class TestResync:
    def test_it_follows_ml_ops_gestionar(self, client, rows, manager, pricing) -> None:
        assert body_of(client, manager)["can_resync"] is True

    def test_a_reader_cannot(self, client, rows, reader, pricing) -> None:
        assert body_of(client, reader)["can_resync"] is False

    def test_ver_ganancia_does_not_grant_it(self, client, rows, analyst, pricing) -> None:
        assert body_of(client, analyst)["can_resync"] is False


class TestFreshness:
    def by_resource(self, body: dict) -> dict:
        return {entry["resource"]: entry for entry in body["freshness"]}

    def test_the_resources_of_a_full_publication_in_a_fixed_order(self, client, rows, reader, pricing) -> None:
        assert [e["resource"] for e in body_of(client, reader)["freshness"]] == [
            "items",
            "description",
            "prices",
            "sale_price",
            "promotions",
            "competition",
            "moderation",
            "performance",
            "visits",
            "user_product",
            "stock",
            "family",
            "replenishment",
        ]

    def test_the_states_are_honest(self, client, rows, reader, pricing) -> None:
        got = self.by_resource(body_of(client, reader))
        assert got["items"]["state"] == "ok" and got["items"]["fetched_at"] is not None
        assert got["description"]["state"] == "ok" and got["description"]["last_checked_at"] is not None
        assert got["moderation"]["state"] == "not_found" and got["moderation"]["http_status"] == 404
        assert got["visits"]["state"] == "error" and got["visits"]["http_status"] == 500
        assert got["family"]["state"] == "ok" and got["replenishment"]["state"] == "ok"
        for never in ("prices", "promotions", "competition", "performance", "user_product"):
            assert got[never] == {
                "resource": never,
                "state": "never_fetched",
                "fetched_at": None,
                "last_checked_at": None,
                "http_status": None,
            }

    def test_only_what_applies_is_listed(self, client, rows, reader, pricing) -> None:
        names = [e["resource"] for e in body_of(client, reader, "MLA12")["freshness"]]
        # no user product, no family, not Full: no user product, stock, family or replenishment
        assert names == [
            "items",
            "description",
            "prices",
            "sale_price",
            "promotions",
            "competition",
            "moderation",
            "performance",
            "visits",
        ]

    def test_a_gone_publication_says_gone(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, lambda conn: seed.add_item(conn, "MLA91", gone_at=seed.NOW, http_status=404))
        assert self.by_resource(body_of(client, reader, "MLA91"))["items"]["state"] == "gone"


class TestStatements:
    def count(self, client, pg, headers, item_id: str, **params) -> list[str]:
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        event.listen(pg, "before_cursor_execute", record)
        try:
            assert detail_of(client, headers, item_id, **params).status_code == 200
        finally:
            event.remove(pg, "before_cursor_execute", record)
        return recorded

    def many(self, conn) -> None:
        conn.execute(text("INSERT INTO ml_tiendas_oficiales (store_id, nombre) VALUES (2645, 'TP-Link')"))
        conn.execute(text("INSERT INTO subcategorias_grupos (subcat_id, grupo_id) VALUES (3845, 1)"))
        for item_id, cost in COST.items():
            seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}", subcategoria_id=3845)
            seed.add_cost(conn, item_id, cost)
        for item_id, n in (("MLA30", 2), ("MLA31", 250)):
            priced(conn, item_id, logistic_type="fulfillment", user_product_id=f"U{item_id}", official_store_id=2645)
            seed.add_link(conn, item_id, 72)
            seed.add_replenishment(conn, f"U{item_id}", units_30d=1)
            for variation in range(1, n + 1):
                seed.add_variation(conn, item_id, variation, seller_sku=f"S{variation}")
                seed.add_link(conn, item_id, 70 + variation % 2, variation_id=variation)

    @pytest.mark.parametrize("margin", [False, True])
    @pytest.mark.parametrize("events", [False, True])
    def test_two_variations_and_two_hundred_fifty_cost_the_same_at_most_eight(
        self, client, pg, request, pricing, margin, events
    ) -> None:
        seed_rows(pg, self.many)
        settings_store.set_setting("events.enabled", events, "test")
        headers = request.getfixturevalue("analyst" if margin else "reader")
        self.count(client, pg, headers, "MLA30")  # warm the caches (permissions, settings)
        small = self.count(client, pg, headers, "MLA30")
        large = self.count(client, pg, headers, "MLA31")
        assert len(small) == len(large), (small, large)
        assert len(small) <= 8, small  # the shipping batch is separate (stubbed here) and is the +1
        assert len(detail_of(client, headers, "MLA31").json()["links"]) == 251

    def test_the_read_is_bounded_in_time_before_the_item_is_read(self, client, rows, pg, reader, pricing) -> None:
        self.count(client, pg, reader, "MLA10")
        statements = self.count(client, pg, reader, "MLA10")
        bound = next(i for i, s in enumerate(statements) if "SET LOCAL statement_timeout" in s)
        item = next(i for i, s in enumerate(statements) if "FROM ml_items" in s and "ml_item_product_links" in s)
        assert bound < item and detail.STATEMENT_TIMEOUT == "3s"

    def test_the_shipping_batch_runs_once_whatever_the_variations(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, self.many)
        detail_of(client, analyst, "MLA31")
        assert len(pricing) == 1

    def test_a_slow_query_is_a_controlled_503(self, client, rows, pg, reader, pricing, monkeypatch) -> None:
        real = detail._item_select

        def slow(*args, **kwargs):
            from sqlalchemy import func

            return real(*args, **kwargs).add_columns(func.pg_sleep(1))

        monkeypatch.setattr(detail, "STATEMENT_TIMEOUT", "50ms")
        monkeypatch.setattr(detail, "_item_select", slow)
        response = detail_of(client, reader)
        assert response.status_code == 503 and response.json()["error"]["code"] == "consulta_lenta"
        assert pg.pool.checkedout() == 0
        monkeypatch.setattr(detail, "STATEMENT_TIMEOUT", "3s")
        monkeypatch.setattr(detail, "_item_select", real)
        assert detail_of(client, reader).status_code == 200


class TestLocaleIndependence:
    def test_nothing_is_ordered_by_text(self) -> None:
        """CI and a developer's Postgres have different collations (what broke P7a): the only ORDER BY of the module
        is on the integer variation id, and the freshness order is a fixed list."""
        source = Path(detail.__file__).read_text(encoding="utf-8")
        # integers and timestamps only: the variation id, and the event time and id (`newest`)
        assert sorted(re.findall(r"order_by\(([^)]*)\)", source)) == ["*newest", "*newest", "link.variation_id"]
        assert "ORDER BY" not in source.upper().replace("ORDER_BY", "")
        assert not re.search(r"\b(min|max)\(", source)  # no string min/max either
        assert detail.RESOURCE_ORDER[0] == "items" and len(set(detail.RESOURCE_ORDER)) == len(detail.RESOURCE_ORDER)


class TestExtraFields:
    """The pure whitelist over a real captured item body (no database)."""

    def test_the_captured_item_yields_every_whitelisted_field(self) -> None:
        extra = detail.extra_fields(CAPTURED)
        assert set(extra) == set(detail.EXTRA_FIELDS)
        assert extra["channels"] == CAPTURED["channels"] and extra["warranty"] == CAPTURED["warranty"]
        assert extra["accepts_mercadopago"] is CAPTURED["accepts_mercadopago"]
        assert extra["shipping"] == {
            "mode": CAPTURED["shipping"]["mode"],
            "local_pick_up": CAPTURED["shipping"]["local_pick_up"],
            "store_pick_up": CAPTURED["shipping"]["store_pick_up"],
            "tags": CAPTURED["shipping"]["tags"],
        }

    def test_lists_of_objects_keep_only_what_is_shown(self) -> None:
        extra = detail.extra_fields(CAPTURED)
        assert [set(a) for a in extra["attributes"]] == [{"id", "name", "value_name"}] * len(CAPTURED["attributes"])
        assert [set(t) for t in extra["sale_terms"]] == [{"id", "name", "value_name"}] * len(CAPTURED["sale_terms"])
        assert [set(p) for p in extra["pictures"]] == [{"id", "secure_url", "size", "max_size"}] * len(
            CAPTURED["pictures"]
        )

    def test_nothing_outside_the_whitelist_leaks(self) -> None:
        extra = detail.extra_fields({**CAPTURED, "secret": "x", "seller_contact": {"phone": "1"}})
        assert "secret" not in extra and "seller_contact" not in extra
        assert "seller_address" not in extra  # the seller is the company itself: its address says nothing

    @pytest.mark.parametrize("raw", [None, {}, [], "x", {"shipping": "x", "attributes": "x"}])
    def test_anything_else_is_all_none(self, raw) -> None:
        extra = detail.extra_fields(raw)
        assert set(extra) == set(detail.EXTRA_FIELDS) and all(value is None for value in extra.values())
