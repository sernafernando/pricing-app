"""P7b.T1 (HTTP): the markup figures of the nodes of `GET /api/ml-publications/view/groups`.

The figures are the flat node fields `negative_count`, `markup_min` and `markup_max`. They exist only for a caller with
`ml_metricas.ver_ganancia`; without it the node is byte-identical to P7a's. The aggregation itself is pinned in
`view/test_group_markup_postgres.py`; this file pins the permission, the wire contract and the Ads parameters.
"""

# ruff: noqa: F811 -- the fixtures are imported from the markup test module and used by name

from __future__ import annotations

import pytest
from sqlalchemy import event

from tests.routers.test_ml_publications_view import get as get_items, seed_rows
from tests.routers.test_ml_publications_view_groups import get
from tests.routers.test_ml_publications_view_ads import PERIOD, FakeAds, _seller, provide, sell  # noqa: F401
from tests.routers.test_ml_publications_view_markup import analyst, pg, pricing, reader, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view.test_group_markup_postgres import seed_catalog, worst_of

pytestmark = pytest.mark.postgres

FIGURES = {"negative_count", "markup_min", "markup_max"}


def node_of(response, key: str) -> dict:
    assert response.status_code == 200, response.text
    return next(n for n in response.json()["nodes"] if n["key"] == key)


class TestGating:
    def test_without_ver_ganancia_a_node_has_none_of_the_figures_and_nothing_is_computed(
        self, client, pg, reader, pricing
    ) -> None:
        seed_rows(pg, seed_catalog)
        response = get(client, reader)
        assert all(not FIGURES & set(n) for n in response.json()["nodes"])
        assert pricing == []

    def test_restar_publicidad_without_ver_ganancia_is_403_as_in_items(self, client, pg, reader, pricing) -> None:
        seed_rows(pg, seed_catalog)
        assert get(client, reader, restar_publicidad="true").status_code == 403


class TestContract:
    def test_a_node_carries_the_count_the_negative_count_and_the_range_and_no_average(
        self, client, pg, analyst, pricing
    ) -> None:
        seed_rows(pg, seed_catalog)
        node = node_of(get(client, analyst), "ALFA")
        assert node["count"] == 2 and node["negative_count"] == 1
        assert node["markup_min"] == round(worst_of(71), 2) and node["markup_max"] == round(worst_of(70), 2)
        assert not {"markup_avg", "markup_mean", "ads", "ads_total"} & set(node)

    def test_a_node_with_no_value_has_a_null_range(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, seed_catalog)
        node = node_of(get(client, analyst, q="MLA3"), "__none__")
        assert node["negative_count"] == 0 and node["markup_min"] is None and node["markup_max"] is None

    def test_the_figures_are_the_only_addition_to_the_p7a_node(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, seed_catalog)
        p7a = {"kind", "key", "label", "count", "leaf", "params"}
        for node in get(client, analyst).json()["nodes"]:
            assert set(node) == p7a | FIGURES

    def test_the_figures_come_with_every_level_of_the_tree(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, seed_catalog)
        response = get(client, analyst, path="ALFA,__none__,3845")
        assert response.json()["level"] == "producto"
        assert all(FIGURES <= set(n) for n in response.json()["nodes"])


class TestAds:
    def test_the_ads_block_says_what_happened_and_is_absent_without_ver_ganancia(
        self, client, pg, analyst, pricing
    ) -> None:
        seed_rows(pg, seed_catalog)
        ads = get(client, analyst, restar_publicidad="true", **PERIOD).json()["ads"]
        assert ads["requested"] is True and ads["applied"] is False and ads["available"] is False

    def test_with_restar_publicidad_the_negative_count_equals_the_items_markup_neg_total(
        self, client, pg, analyst, pricing, provide, db
    ) -> None:
        seed_rows(pg, seed_catalog)
        sell(db, "MLA1", 4, 1001)  # 400000 of Ads over 4 units turns MLA1 negative
        sell(db, "MLA6", 2, 1002)
        provide(FakeAds({"MLA1": 400000.0, "MLA6": 200000.0}))
        plain = {n["key"]: n["negative_count"] for n in get(client, analyst).json()["nodes"]}
        response = get(client, analyst, restar_publicidad="true", **PERIOD)
        assert response.json()["ads"]["applied"] is True
        for node in response.json()["nodes"]:
            total = get_items(client, analyst, markup_neg="true", restar_publicidad="true", **PERIOD, **node["params"])
            assert node["negative_count"] == total.json()["total"], node["params"]
        assert {n["key"]: n["negative_count"] for n in response.json()["nodes"]} != plain

    def test_a_malformed_period_is_422_as_in_items(self, client, pg, analyst, pricing) -> None:
        seed_rows(pg, seed_catalog)
        assert get(client, analyst, ads_desde="yesterday", ads_hasta="2026-09-01").status_code == 422


class TestCost:
    @staticmethod
    def statements(client, pg, headers, **params) -> list[str]:
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        event.listen(pg, "before_cursor_execute", record)
        try:
            assert get(client, headers, **params).status_code == 200
        finally:
            event.remove(pg, "before_cursor_execute", record)
        return recorded

    def test_the_statements_do_not_grow_with_the_number_of_nodes_and_the_shipping_is_one_batch(
        self, client, pg, analyst, pricing
    ) -> None:
        seed_rows(pg, seed_catalog)
        self.statements(client, pg, analyst)  # warm
        pricing.clear()
        one = self.statements(client, pg, analyst, limit=1)
        assert len(pricing) == 1
        pricing.clear()
        three = self.statements(client, pg, analyst, limit=100)
        assert len(three) == len(one) and len(pricing) == 1
