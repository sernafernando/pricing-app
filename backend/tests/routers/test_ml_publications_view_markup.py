"""P6.T3: markup in `GET /api/ml-publications/view/items` (gating, range, sort by the worst variation, filters).

Same harness as `test_ml_publications_view.py` (permissions in the SQLite test database, the store in a throwaway
Postgres schema). The pricing context and the real shipping batch are stubbed with the hand-built ones of
`test_unit_markup.py`: this file pins the HTTP contract and the set-wide/page paths, not the maths (P2).
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.services.ml_publications.view import markup_service
from app.services.ml_publications.view.markup import unit_markup
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import (  # noqa: F401
    GANANCIA,
    URL,
    VER,
    get,
    pg as view_pg,
    seed_rows,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_unit_markup import make_ctx, make_inputs

pytestmark = pytest.mark.postgres

COST = {70: 40000.0, 71: 60000.0, 72: 50000.0, 73: 45000.0}


@pytest.fixture()
def pg(view_pg):  # noqa: F811 -- the imported fixture is used by name
    """The store behind the router (see `test_ml_publications_view.pg`)."""
    return view_pg


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def analyst(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, GANANCIA)
    return admin_auth_headers


@pytest.fixture()
def pricing(monkeypatch):
    """The pricing context and the shipping batch, stubbed; the batch calls are recorded."""
    calls: list[list[int]] = []
    monkeypatch.setattr(markup_service, "build_pricing_context", lambda db: make_ctx())

    def envio(db, product_ids, **kwargs):
        calls.append(list(product_ids))
        return {}

    monkeypatch.setattr(markup_service, "resolver_costos_envio_batch", envio)
    return calls


def fill(conn) -> None:
    """Worst variation: MLA2 = MLA4 (lowest) < MLA5 < MLA6 < MLA1; MLA3 has no link (no markup)."""
    for item_id, cost in COST.items():
        seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}", subcategoria_id=3845)
        seed.add_cost(conn, item_id, cost)
    for number, title in ((1, "Alfa"), (2, "Bravo"), (3, "Charlie"), (4, "Delta"), (5, "Eco"), (6, "Foxtrot")):
        seed.add_item(
            conn,
            f"MLA{number}",
            title=title,
            listing_type_id="gold_pro",
            tags=["9x_campaign"],
            price=90000,
            last_trigger_received_at=seed.hours_ago(number),
        )
        seed.add_sale_price(conn, f"MLA{number}", 100000)
    seed.add_link(conn, "MLA1", 70)
    seed.add_link(conn, "MLA2", 71)
    seed.add_variation(conn, "MLA4", 11)
    seed.add_variation(conn, "MLA4", 12)
    seed.add_link(conn, "MLA4", 70, variation_id=11)
    seed.add_link(conn, "MLA4", 71, variation_id=12)
    seed.add_link(conn, "MLA5", 72)
    seed.add_link(conn, "MLA6", 73)


def worst_of(product: int) -> float:
    value = unit_markup(make_ctx(), make_inputs(producto_item_id=product, costo=COST[product]), {}).value
    assert value is not None
    return value


def ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [row["item_id"] for row in response.json()["items"]]


def test_the_fixture_has_the_signs_the_expectations_below_rely_on() -> None:
    assert worst_of(71) < worst_of(72) < 0 < worst_of(73) < worst_of(70)


class TestGating:
    def test_without_ver_ganancia_the_response_has_no_markup_keys_at_all(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, fill)
        body = get(client, reader).json()
        assert not {"markup_stats", "ads"} & set(body)
        assert all("markup" not in row for row in body["items"])
        assert pricing == []  # nothing was even computed

    @pytest.mark.parametrize(
        "params",
        [
            {"orden": "markup"},
            {"markup_neg": "true"},
            {"markup_min": "0"},
            {"markup_max": "10"},
            {"restar_publicidad": "true"},
        ],
    )
    def test_markup_parameters_without_ver_ganancia_are_403(self, client, pg, reader, pricing, params) -> None:
        seed_rows(pg, fill)
        response = get(client, reader, **params)
        assert response.status_code == 403
        assert GANANCIA in response.json()["error"]["message"]

    def test_false_flags_are_not_markup_parameters(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, fill)
        assert get(client, reader, markup_neg="false", restar_publicidad="false").status_code == 200

    def test_with_ver_ganancia_each_row_carries_its_markup_and_the_request_its_stats(
        self, client, pg, analyst, pricing
    ) -> None:
        seed_rows(pg, fill)
        body = get(client, analyst).json()
        rows = {row["item_id"]: row for row in body["items"]}
        assert rows["MLA1"]["markup"] == {
            "min": round(worst_of(70), 2),
            "max": round(worst_of(70), 2),
            "worst": round(worst_of(70), 2),
            "any_negative": False,
            "reason": "ok",
            "partial": 0,
        }
        assert rows["MLA3"]["markup"] == {
            "min": None,
            "max": None,
            "worst": None,
            "any_negative": False,
            "reason": "sin_vinculo",
            "partial": 0,
        }
        assert body["markup_stats"]["computed"] == 5
        assert body["markup_stats"]["null_by_reason"] == {"sin_vinculo": 1}
        assert body["markup_stats"]["ms"] >= 0

    def test_a_publication_with_variations_shows_the_range_the_worst_and_any_negative(
        self, client, pg, analyst, pricing
    ) -> None:
        seed_rows(pg, fill)
        row = next(r for r in get(client, analyst).json()["items"] if r["item_id"] == "MLA4")
        assert row["markup"]["min"] == row["markup"]["worst"] == round(worst_of(71), 2)
        assert row["markup"]["max"] == round(worst_of(70), 2)
        assert row["markup"]["any_negative"] is True

    def test_the_page_path_prices_only_the_products_of_the_page_in_one_batch(
        self, client, pg, analyst, pricing
    ) -> None:
        seed_rows(pg, fill)
        get(client, analyst, limit=2)  # MLA1 and MLA2 are the most recent
        assert pricing == [[70, 71]]


class TestSort:
    def test_orden_markup_sorts_by_the_worst_variation_nulls_last(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        assert ids(get(client, analyst, orden="markup", dir="asc")) == [
            "MLA2",
            "MLA4",
            "MLA5",
            "MLA6",
            "MLA1",
            "MLA3",
        ]

    def test_descending_keeps_the_nulls_last_and_ties_by_item_id(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        assert ids(get(client, analyst, orden="markup", dir="desc")) == [
            "MLA1",
            "MLA6",
            "MLA5",
            "MLA2",
            "MLA4",
            "MLA3",
        ]

    def test_the_default_direction_puts_the_worst_first(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        assert ids(get(client, analyst, orden="markup"))[:2] == ["MLA2", "MLA4"]

    def test_the_order_holds_across_pages_and_the_total_is_the_set(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        pages = [get(client, analyst, orden="markup", limit=2, offset=offset) for offset in (0, 2, 4)]
        assert [ids(page) for page in pages] == [["MLA2", "MLA4"], ["MLA5", "MLA6"], ["MLA1", "MLA3"]]
        assert {page.json()["total"] for page in pages} == {6}
        assert ids(get(client, analyst, orden="markup", limit=2, offset=6)) == []

    def test_the_sorted_pages_carry_the_markup_computed_for_the_whole_set(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        body = get(client, analyst, orden="markup", limit=2).json()
        assert [row["markup"]["worst"] for row in body["items"]] == [round(worst_of(71), 2)] * 2
        assert len(pricing) == 1  # one shipping batch for the whole set, not one per page
        assert body["markup_stats"]["computed"] == 5


class TestFilters:
    def test_markup_neg_is_any_variation_negative_and_nulls_are_excluded(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        response = get(client, analyst, markup_neg="true", orden="titulo")
        assert ids(response) == ["MLA2", "MLA4", "MLA5"]  # MLA4: one variation is positive, another negative
        assert response.json()["total"] == 3

    def test_min_and_max_apply_to_the_worst_variation(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        assert ids(get(client, analyst, markup_min="0", orden="titulo")) == ["MLA1", "MLA6"]
        assert ids(get(client, analyst, markup_max="0", orden="titulo")) == ["MLA2", "MLA4", "MLA5"]
        between = get(client, analyst, markup_min=str(worst_of(72) - 1), markup_max="10", orden="titulo")
        assert ids(between) == ["MLA5", "MLA6"]

    def test_a_filter_without_orden_markup_keeps_the_requested_order_and_pages_the_filtered_set(
        self, client, pg, analyst, pricing
    ) -> None:
        seed_rows(pg, fill)
        first = get(client, analyst, markup_neg="true", orden="titulo", limit=2)
        second = get(client, analyst, markup_neg="true", orden="titulo", limit=2, offset=2)
        assert (ids(first), ids(second)) == (["MLA2", "MLA4"], ["MLA5"])
        assert first.json()["total"] == second.json()["total"] == 3

    def test_markup_filters_compose_with_the_other_filters(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        assert ids(get(client, analyst, markup_neg="true", q="Bravo")) == ["MLA2"]
        assert ids(get(client, analyst, markup_neg="true", estado="paused")) == []

    def test_a_filter_matching_nothing_is_an_empty_page(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, fill)
        body = get(client, analyst, markup_min="1000").json()
        assert (body["items"], body["total"]) == ([], 0)

    @pytest.mark.parametrize("params", [{"markup_min": "abc"}, {"markup_max": "x"}, {"markup_min": "nan"}])
    def test_a_malformed_number_is_422_naming_the_parameter(self, client, pg, analyst, pricing, params) -> None:
        response = get(client, analyst, **params)
        assert response.status_code == 422
        assert response.json()["error"]["field"] == next(iter(params))

    def test_min_above_max_is_422(self, client, pg, analyst, pricing) -> None:
        response = get(client, analyst, markup_min="10", markup_max="1")
        assert response.status_code == 422 and response.json()["error"]["field"] == "markup_min"


class TestStatements:
    def statements(self, client, pg, headers, **params) -> list[str]:
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        event.listen(pg, "before_cursor_execute", record)
        try:
            assert client.get(URL, headers=headers, params=params).status_code == 200
        finally:
            event.remove(pg, "before_cursor_execute", record)
        return recorded

    def seed_many(self, conn) -> None:
        seed.add_product(conn, 70, "C70", "Producto", subcategoria_id=3845)
        seed.add_cost(conn, 70, 40000.0)
        for number in range(1, 121):
            seed.add_item(conn, f"MLA{number}", listing_type_id="gold_pro", price=90000, tags=["9x_campaign"])
            seed.add_link(conn, f"MLA{number}", 70)

    @pytest.mark.parametrize("params", [{}, {"orden": "markup"}, {"markup_neg": "true"}])
    def test_ten_rows_and_a_hundred_rows_cost_the_same_number_of_statements(
        self, client, pg, analyst, pricing, params
    ) -> None:
        seed_rows(pg, self.seed_many)
        client.get(URL, headers=analyst)  # warm: the status block is built once and then served from its cache
        small = self.statements(client, pg, analyst, limit=10, **params)
        large = self.statements(client, pg, analyst, limit=100, **params)
        assert len(small) == len(large)
        assert len(small) <= 14, small  # page: count + rows + 3 extras + 3 for the markup inputs, plus the rest
