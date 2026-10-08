"""P6c.T1: `GET /api/ml-publications/view/items/{item_id}/variations`, the sub-rows of an expanded publication.

Same harness as the list's markup tests (permissions in the SQLite test database, the store in a throwaway
Postgres schema). The pricing context and the real shipping batch are stubbed with the hand-built ones of
`test_unit_markup.py`: this file pins the HTTP contract, the link fallback, the gating and the statement count,
not the maths (P2) and not the Ads formulas (P6).
"""

# ruff: noqa: F811 -- the fixtures are imported from the list's test modules and used by name

from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy import event

from app.services.ml_publications.view import ads as ads_module
from app.services.ml_publications.view import markup_service, variations
from app.services.ml_publications.view.markup import unit_markup
from tests.routers.test_ml_publications_view import seed_rows
from tests.routers.test_ml_publications_view_ads import (  # noqa: F401
    PERIOD,
    Exploding,
    FakeAds,
    _seller,
    provide,
    sell,
)
from tests.routers.test_ml_publications_view_markup import (  # noqa: F401
    COST,
    analyst,
    pg,
    pricing,
    reader,
    view_pg,
    worst_of,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_unit_markup import make_ctx, make_inputs

pytestmark = pytest.mark.postgres

BASE = "/api/ml-publications/view/items"
COLOR = {"attribute_combinations": [{"id": "COLOR", "name": "Color", "value_id": "1", "value_name": "Rojo"}]}


def url(item_id: str) -> str:
    return f"{BASE}/{item_id}/variations"


def variations_of(client, headers, item_id: str = "MLA10", **params):
    return client.get(url(item_id), headers=headers, params=params)


def priced(conn, item_id: str, **columns) -> None:
    """A publication on the 9x list with a sale price, like the list tests': the markup of product `n` is `worst_of(n)`."""
    seed.add_item(conn, item_id, listing_type_id="gold_pro", tags=["9x_campaign"], price=90000, **columns)
    seed.add_sale_price(conn, item_id, 100000)


def fill(conn) -> None:
    """MLA10: item-level link to 72; variation 11 -> 70 (auto), 12 -> 71 (manual), 13 has no link of its own (falls
    back to 72), 14 is gone. MLA11: one variation, nothing linked anywhere. MLA12: no variations."""
    for item_id, cost in COST.items():
        seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}", marca=f"M{item_id}", subcategoria_id=3845)
        seed.add_cost(conn, item_id, cost)
    priced(conn, "MLA10", title="Camara", available_quantity=30)
    seed.add_link(conn, "MLA10", 72)
    seed.add_variation(
        conn,
        "MLA10",
        11,
        seller_sku="SKU-A",
        user_product_id="MLAU11",
        available_quantity=10,
        sold_quantity=4,
        raw={"id": 11, **COLOR},
    )
    seed.add_variation(conn, "MLA10", 12, seller_custom_field="CUSTOM-B", available_quantity=5, sold_quantity=0)
    seed.add_variation(conn, "MLA10", 13, available_quantity=15, sold_quantity=2)
    seed.add_variation(conn, "MLA10", 14, seller_sku="GONE", gone_at=seed.NOW)
    seed.add_link(conn, "MLA10", 70, variation_id=11)
    seed.add_link(conn, "MLA10", 71, variation_id=12, source="manual")
    priced(conn, "MLA11")
    seed.add_variation(conn, "MLA11", 21, seller_sku="LONELY")
    priced(conn, "MLA12")
    seed.add_link(conn, "MLA12", 70)


@pytest.fixture()
def rows(pg):
    seed_rows(pg, fill)


def by_id(response) -> dict[int, dict]:
    assert response.status_code == 200, response.text
    return {v["variation_id"]: v for v in response.json()["variations"]}


class TestContract:
    def test_one_sub_row_per_live_variation_ordered_by_id(self, client, rows, reader, pricing) -> None:
        body = variations_of(client, reader).json()
        assert body["item_id"] == "MLA10" and body["can_see_margin"] is False
        assert [v["variation_id"] for v in body["variations"]] == [11, 12, 13]  # 14 is gone

    def test_the_variation_own_data(self, client, rows, reader, pricing) -> None:
        got = by_id(variations_of(client, reader))
        assert got[11]["seller_sku"] == "SKU-A" and got[11]["user_product_id"] == "MLAU11"
        assert (got[11]["available_quantity"], got[11]["sold_quantity"]) == (10, 4)
        assert got[11]["attributes"] == [{"name": "Color", "value": "Rojo"}]
        assert got[12]["seller_sku"] == "CUSTOM-B"  # the SKU the linking reads: the attribute, else the custom field
        assert got[12]["attributes"] == [] and got[13]["seller_sku"] is None

    def test_each_sub_row_shows_the_product_it_is_priced_with(self, client, rows, reader, pricing) -> None:
        got = by_id(variations_of(client, reader))
        assert got[11]["link"] == {
            "state": "auto",
            "inherited": False,
            "producto_item_id": 70,
            "codigo": "C70",
            "descripcion": "Producto 70",
            "marca": "M70",
        }
        assert got[12]["link"]["state"] == "manual" and got[12]["link"]["producto_item_id"] == 71
        # no link of its own: the item-level one, flagged
        assert got[13]["link"] == {
            "state": "auto",
            "inherited": True,
            "producto_item_id": 72,
            "codigo": "C72",
            "descripcion": "Producto 72",
            "marca": "M72",
        }

    def test_nothing_linked_anywhere_reads_no_evaluado(self, client, rows, reader, pricing) -> None:
        link = by_id(variations_of(client, reader, "MLA11"))[21]["link"]
        assert link == {
            "state": "no_evaluado",
            "inherited": True,
            "producto_item_id": None,
            "codigo": None,
            "descripcion": None,
            "marca": None,
        }

    def test_a_publication_without_variations_has_no_sub_rows(self, client, rows, reader, pricing) -> None:
        assert variations_of(client, reader, "MLA12").json()["variations"] == []


class TestErrors:
    def test_unknown_item_is_404(self, client, rows, reader, pricing) -> None:
        response = variations_of(client, reader, "MLA404")
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.parametrize("item_id", ["mla10", "MLA", "10", "MLA1x"])
    def test_a_malformed_id_is_422(self, client, rows, reader, pricing, item_id) -> None:
        assert variations_of(client, reader, item_id).status_code == 422

    def test_without_ml_ops_ver_it_is_403(self, client, rows, auth_headers, pricing) -> None:
        response = variations_of(client, auth_headers)
        assert response.status_code == 403 and "ml_ops.ver" in response.json()["error"]["message"]

    def test_authentication_is_required(self, client, rows, pricing) -> None:
        assert client.get(url("MLA10")).status_code in (401, 403)

    def test_asking_for_ads_without_ver_ganancia_is_403(self, client, rows, reader, pricing) -> None:
        response = variations_of(client, reader, restar_publicidad="true", **PERIOD)
        assert response.status_code == 403 and "ml_metricas.ver_ganancia" in response.json()["error"]["message"]


class TestMargin:
    def test_without_ver_ganancia_cost_markup_and_ads_are_omitted(self, client, rows, reader, pricing) -> None:
        body = variations_of(client, reader).json()
        assert "ads" not in body
        assert all({"costo", "markup"}.isdisjoint(v) for v in body["variations"])
        assert pricing == []  # not even the shipping batch ran

    def test_cost_and_markup_per_sub_row_with_the_fallback_unit(self, client, rows, analyst, pricing) -> None:
        got = by_id(variations_of(client, analyst))
        for variation, product in ((11, 70), (12, 71), (13, 72)):
            assert got[variation]["costo"] == {"amount": COST[product], "currency": "ARS"}
            assert got[variation]["markup"] == {"value": round(worst_of(product), 2), "reason": "ok"}
        assert pricing == [[70, 71, 72]]  # ONE shipping batch for the publication

    def test_it_is_the_unit_markup_of_the_stored_inputs(self, client, rows, analyst, pricing) -> None:
        expected = unit_markup(make_ctx(), make_inputs(producto_item_id=70, costo=COST[70]), {}).value
        assert by_id(variations_of(client, analyst))[11]["markup"]["value"] == round(expected, 2)

    def test_what_cannot_be_priced_says_why_and_is_never_zero(self, client, rows, analyst, pricing) -> None:
        sub = by_id(variations_of(client, analyst, "MLA11"))[21]
        assert sub["markup"] == {"value": None, "reason": "sin_vinculo"} and sub["costo"] is None

    def test_a_product_without_cost_has_a_null_cost_and_sin_costo(self, client, pg, analyst, pricing) -> None:
        def sparse(conn) -> None:
            seed.add_product(conn, 80, "C80", "Sin costo", subcategoria_id=3845)
            seed.add_cost(conn, 80, None)
            priced(conn, "MLA20")
            seed.add_variation(conn, "MLA20", 1)
            seed.add_link(conn, "MLA20", 80, variation_id=1)

        seed_rows(pg, sparse)
        sub = by_id(variations_of(client, analyst, "MLA20"))[1]
        assert sub["markup"] == {"value": None, "reason": "sin_costo"}
        assert sub["costo"] == {"amount": None, "currency": "ARS"}


class TestAds:
    def test_the_per_unit_cost_is_the_same_on_every_sub_row(self, client, rows, analyst, pricing, provide, db) -> None:
        provide(FakeAds({"MLA10": 12000.0}))
        sell(db, "MLA10", 6, 2001)  # 12000 over 6 units: 2000 each, whatever the variation
        body = variations_of(client, analyst, restar_publicidad="true", **PERIOD).json()
        assert body["ads"] == {
            "available": True,
            "reason": "ok",
            "requested": True,
            "applied": True,
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
            "publication": {"state": "ok", "amount": 12000.0, "units": 6, "per_unit": 2000.0},
        }
        formula = ads_module.ADS_MARKUP_FORMULAS["costo_extra"]
        for sub in body["variations"]:
            product = sub["link"]["producto_item_id"]
            unit = unit_markup(make_ctx(), make_inputs(producto_item_id=product, costo=COST[product]), {})
            expected = formula(unit.limpio, unit.costo_ars, 2000.0)
            assert sub["markup"] == {"value": round(expected, 2), "reason": "ok"}
            assert sub["markup"]["value"] < round(worst_of(product), 2)

    def test_ads_cost_without_sales_blanks_the_markup_and_keeps_the_amount(
        self, client, rows, analyst, pricing, provide
    ) -> None:
        provide(FakeAds({"MLA10": 5000.0}))
        body = variations_of(client, analyst, restar_publicidad="true", **PERIOD).json()
        assert body["ads"]["publication"] == {"state": "ads_sin_ventas", "amount": 5000.0, "units": 0, "per_unit": None}
        assert {v["markup"]["reason"] for v in body["variations"]} == {"ads_sin_ventas"}
        assert {v["markup"]["value"] for v in body["variations"]} == {None}
        assert [v["costo"]["amount"] for v in body["variations"]] == [COST[70], COST[71], COST[72]]

    def test_a_publication_without_ads_cost_keeps_the_plain_markup(
        self, client, rows, analyst, pricing, provide
    ) -> None:
        provide(FakeAds({"MLA11": 999.0}))
        response = variations_of(client, analyst, restar_publicidad="true", **PERIOD)
        assert response.json()["ads"]["publication"]["state"] == "sin_costo"
        assert by_id(response)[11]["markup"]["value"] == round(worst_of(70), 2)

    def test_the_provider_is_asked_for_this_publication_only(self, client, rows, analyst, pricing, provide) -> None:
        fake = FakeAds({})
        provide(fake)
        variations_of(client, analyst, restar_publicidad="true", **PERIOD)
        assert [call[0] for call in fake.calls] == [["MLA10"]]

    def test_without_the_request_there_is_the_status_but_no_publication_figures(
        self, client, rows, analyst, pricing, provide
    ) -> None:
        provide(FakeAds({"MLA10": 12000.0}))
        ads = variations_of(client, analyst).json()["ads"]
        assert ads == {"available": True, "reason": "ok", "requested": False, "applied": False}

    def test_a_provider_that_raises_degrades_to_the_plain_markup(self, client, rows, analyst, pricing, provide) -> None:
        provide(Exploding("amounts"))
        response = variations_of(client, analyst, restar_publicidad="true", **PERIOD)
        assert response.status_code == 200
        assert response.json()["ads"]["reason"] == "provider_error" and response.json()["ads"]["applied"] is False
        assert by_id(response)[11]["markup"]["value"] == round(worst_of(70), 2)

    def test_applying_ads_requires_the_period(self, client, rows, analyst, pricing, provide) -> None:
        provide(FakeAds({}))
        response = variations_of(client, analyst, restar_publicidad="true")
        assert response.status_code == 422 and response.json()["error"]["field"] == "ads_desde"


class TestRace:
    def test_a_variation_replaced_between_statements_never_gets_the_markup_of_another(
        self, client, rows, analyst, pricing, monkeypatch
    ) -> None:
        """Variation 13 went away and a 15 appeared after the sub-rows were read: same count, other id."""
        real = markup_service.compute_markups

        def replaced(*args, **kwargs):
            result = real(*args, **kwargs)
            item = result.items["MLA10"]
            shifted = dataclasses.replace(item, variation_ids=(11, 12, 15))
            return dataclasses.replace(result, items={"MLA10": shifted})

        monkeypatch.setattr(variations.markup_service, "compute_markups", replaced)
        got = by_id(variations_of(client, analyst))
        assert got[13]["markup"] == {"value": None, "reason": "desactualizado"}
        assert got[11]["markup"]["value"] == round(worst_of(70), 2)
        assert got[12]["markup"]["value"] == round(worst_of(71), 2)


class TestStatements:
    def count(self, client, pg, headers, item_id: str, **params) -> list[str]:
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        event.listen(pg, "before_cursor_execute", record)
        try:
            assert variations_of(client, headers, item_id, **params).status_code == 200
        finally:
            event.remove(pg, "before_cursor_execute", record)
        return recorded

    def many(self, conn) -> None:
        for item_id, cost in COST.items():
            seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}", subcategoria_id=3845)
            seed.add_cost(conn, item_id, cost)
        for item_id, n in (("MLA30", 2), ("MLA31", 250)):
            priced(conn, item_id)
            seed.add_link(conn, item_id, 72)
            for variation in range(1, n + 1):
                seed.add_variation(conn, item_id, variation, seller_sku=f"S{variation}", raw={"id": variation, **COLOR})
                seed.add_link(conn, item_id, 70 + variation % 2, variation_id=variation)

    @pytest.mark.parametrize("margin", [False, True])
    def test_two_variations_and_two_hundred_fifty_cost_the_same_number_of_statements(
        self, client, pg, request, pricing, margin
    ) -> None:
        seed_rows(pg, self.many)
        headers = request.getfixturevalue("analyst" if margin else "reader")  # both grant the same role: one only
        self.count(client, pg, headers, "MLA30")  # warm the caches (permissions, settings)
        small = self.count(client, pg, headers, "MLA30")
        large = self.count(client, pg, headers, "MLA31")
        assert len(small) == len(large), (small, large)
        # SET LOCAL timeout + the sub-rows; with margins also the three statements of the markup inputs
        assert len(small) <= (5 if margin else 2), small
        assert len(by_id(variations_of(client, headers, "MLA31"))) == 250

    def test_with_ads_the_count_is_constant_too(self, client, pg, analyst, pricing, provide, db) -> None:
        seed_rows(pg, self.many)
        provide(FakeAds({"MLA30": 100.0, "MLA31": 100.0}))
        sell(db, "MLA30", 1, 3001)
        sell(db, "MLA31", 1, 3002)
        params = {"restar_publicidad": "true", **PERIOD}
        self.count(client, pg, analyst, "MLA30", **params)
        small = self.count(client, pg, analyst, "MLA30", **params)
        large = self.count(client, pg, analyst, "MLA31", **params)
        assert len(small) == len(large), (small, large)
