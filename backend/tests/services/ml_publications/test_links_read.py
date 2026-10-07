"""Read side of the product links (P5L2.T3): one item's units with their suggestion, and the
keyset-paginated lists by class. Real Postgres; items are real captures."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core import database
from app.services.ml_publications import links
from tests.services.ml_publications.conftest import item_with_variations, sample_item
from tests.services.ml_publications.test_links_store import ITEM, SKU_A, at, put_link
from tests.services.ml_publications.test_store_apply_fetch import apply

pytestmark = pytest.mark.postgres


def add_described(engine, item_id: int, codigo: str, descripcion: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO productos_erp (item_id, codigo, descripcion) VALUES (:i, :c, :d)"),
            {"i": item_id, "c": codigo, "d": descripcion},
        )


def describe(item_id: str = ITEM) -> dict:
    with database.get_background_db() as db:
        return links.describe_item(db, item_id)


def unit(described: dict, variation_id: int = 0) -> dict:
    return next(u for u in described["units"] if u["variation_id"] == variation_id)


def evaluated(env, item_id: str = ITEM, body=None, minutes: float = 1) -> None:
    apply(body if body is not None else sample_item(item_id), item_id, minutes=minutes)
    with database.get_background_db() as db:
        links.evaluate_for_item(db, item_id, now=at(minutes), events_enabled=False)


class TestDescribeItem:
    def test_an_automatic_link_shows_the_product_and_the_same_suggestion(self, env) -> None:
        add_described(env, 41, SKU_A, "Router AX3000")
        evaluated(env)

        described = describe()

        assert described["item_id"] == ITEM
        assert described["title"] and described["status"]
        assert [u["variation_id"] for u in described["units"]] == [0]
        u = unit(described)
        assert u["live"] is True and u["sku"] == SKU_A and u["sku_field"] == "seller_sku_attr"
        assert u["link"]["source"] == "sku_auto" and u["link"]["match_status"] == "linked"
        assert u["link"]["producto"] == {"item_id": 41, "codigo": SKU_A, "descripcion": "Router AX3000"}
        assert u["link"]["dangling"] is False
        assert u["suggestion"]["status"] == "linked" and u["suggestion"]["producto"]["item_id"] == 41
        assert u["suggestion"]["differs"] is False

    def test_a_conflict_lists_every_candidate_with_its_code_and_description(self, env) -> None:
        add_described(env, 9, SKU_A, "Router A (caja)")
        add_described(env, 5, SKU_A, "Router A (suelto)")
        evaluated(env)

        u = unit(describe())

        assert u["link"]["match_status"] == "conflict" and u["link"]["producto"] is None
        assert u["suggestion"]["status"] == "conflict" and u["suggestion"]["producto"] is None
        assert u["suggestion"]["candidates"] == [
            {"item_id": 5, "codigo": SKU_A, "descripcion": "Router A (suelto)"},
            {"item_id": 9, "codigo": SKU_A, "descripcion": "Router A (caja)"},
        ]

    def test_a_unit_never_evaluated_has_no_link_but_a_live_suggestion(self, env) -> None:
        add_described(env, 41, SKU_A, "Router")
        apply(sample_item(ITEM), ITEM)  # stored, links never evaluated

        u = unit(describe())

        assert u["link"] is None
        assert u["suggestion"]["status"] == "linked" and u["suggestion"]["producto"]["item_id"] == 41

    def test_a_manual_link_that_differs_from_the_suggestion_says_so(self, env) -> None:
        add_described(env, 41, SKU_A, "Router")
        add_described(env, 42, "OTHER", "Switch")
        evaluated(env)
        with env.begin() as conn:
            conn.execute(text("DELETE FROM ml_item_product_links"))
        put_link(
            env, ITEM, 0, "manual", "linked", 42, linked_by=7, note="note", evaluated_sku_key=SKU_A, evaluated_at=at(1)
        )

        u = unit(describe())

        assert u["link"]["source"] == "manual" and u["link"]["producto"]["item_id"] == 42
        assert (u["link"]["linked_by"], u["link"]["note"]) == (7, "note")
        assert u["suggestion"]["producto"]["item_id"] == 41 and u["suggestion"]["differs"] is True

    def test_a_link_to_a_product_that_no_longer_exists_is_dangling(self, env) -> None:
        add_described(env, 41, SKU_A, "Router")
        evaluated(env)
        with env.begin() as conn:
            conn.execute(text("DELETE FROM productos_erp WHERE item_id = 41"))

        u = unit(describe())

        assert u["link"]["dangling"] is True and u["link"]["producto"] is None
        assert u["link"]["producto_item_id"] == 41

    def test_an_item_with_variations_has_one_unit_per_variation(self, env) -> None:
        body = item_with_variations()
        add_described(env, 7, "126", "Cable")
        body["seller_custom_field"] = "126"
        evaluated(env, body["id"], body)

        described = describe(body["id"])

        assert [u["variation_id"] for u in described["units"]] == [
            175550253195,
            175550253196,
            175550253197,
            175550253198,
        ]
        assert {u["link"]["producto"]["item_id"] for u in described["units"]} == {7}

    def test_an_unknown_item_fails_closed(self, env) -> None:
        with pytest.raises(links.UnknownItem):
            describe("MLA1")


def seed(env, rows) -> None:
    for item_id, variation_id, source, status, product, extra in rows:
        put_link(env, item_id, variation_id, source, status, product, evaluated_at=at(1), **extra)


def listing(cls: str, cursor=None, limit: int = 50) -> dict:
    with database.get_background_db() as db:
        return links.list_units(db, cls, cursor=cursor, limit=limit)


def ids(page: dict) -> list[tuple[str, int]]:
    return [(i["item_id"], i["variation_id"]) for i in page["items"]]


class TestLists:
    @pytest.fixture()
    def rows(self, env):
        add_described(env, 41, SKU_A, "Router")
        seed(
            env,
            [
                ("MLA1", 0, "sku_auto", "unmatched", None, {"matched_sku": "X1", "suggestion_status": "unmatched"}),
                ("MLA2", 0, "sku_auto", "conflict", None, {"matched_sku": SKU_A, "candidate_ids": [5, 9]}),
                (
                    "MLA3",
                    0,
                    "manual",
                    "linked",
                    41,
                    {"suggestion_status": "linked", "suggested_producto_item_id": 5},
                ),
                (
                    "MLA4",
                    0,
                    "manual_none",
                    "no_product",
                    None,
                    {"suggestion_status": "linked", "suggested_producto_item_id": 41},
                ),
                ("MLA5", 0, "sku_auto", "linked", 999, {}),  # product 999 is not in the catalog
                ("MLA6", 0, "sku_auto", "linked", 41, {}),
                ("MLA7", 0, "manual", "linked", 41, {"suggestion_status": "linked", "suggested_producto_item_id": 41}),
            ],
        )
        return env

    @pytest.mark.parametrize(
        "cls, expected",
        [
            ("unmatched", [("MLA1", 0)]),
            ("conflict", [("MLA2", 0)]),
            ("manual_differs", [("MLA3", 0), ("MLA4", 0)]),
            ("dangling", [("MLA5", 0)]),
        ],
    )
    def test_each_class_lists_exactly_its_units(self, rows, cls, expected) -> None:
        assert ids(listing(cls)) == expected

    def test_a_list_row_carries_the_link_and_the_suggestion(self, rows) -> None:
        (item,) = listing("manual_differs", limit=1)["items"]
        assert item["source"] == "manual" and item["producto_item_id"] == 41
        assert (item["suggestion_status"], item["suggested_producto_item_id"]) == ("linked", 5)

    def test_an_unknown_class_is_refused(self, env) -> None:
        with pytest.raises(ValueError):
            listing("everything")

    def test_keyset_pages_walk_every_row_once_in_order(self, env) -> None:
        seed(env, [(f"MLA{n}", 0, "sku_auto", "unmatched", None, {}) for n in range(10, 15)])
        seed(env, [("MLA12", 3, "sku_auto", "unmatched", None, {})])

        seen, cursor = [], None
        while True:
            page = listing("unmatched", cursor=cursor, limit=2)
            seen += ids(page)
            cursor = page["next_cursor"]
            if cursor is None:
                break

        assert seen == sorted(seen) and len(seen) == len(set(seen)) == 6
        assert ("MLA12", 3) in seen

    def test_the_last_page_has_no_cursor_and_a_full_last_page_is_not_followed_by_an_empty_one(self, env) -> None:
        seed(env, [(f"MLA{n}", 0, "sku_auto", "unmatched", None, {}) for n in range(10, 14)])
        first = listing("unmatched", limit=2)
        second = listing("unmatched", cursor=first["next_cursor"], limit=2)
        assert first["next_cursor"] is not None
        assert len(second["items"]) == 2 and second["next_cursor"] is None

    def test_pages_stay_stable_when_rows_change_between_requests(self, env) -> None:
        seed(env, [(f"MLA{n}", 0, "sku_auto", "unmatched", None, {}) for n in (20, 30, 40, 50)])
        first = listing("unmatched", limit=2)
        assert ids(first) == [("MLA20", 0), ("MLA30", 0)]
        # between requests: a row before the cursor appears, the cursor row itself leaves the class
        seed(env, [("MLA10", 0, "sku_auto", "unmatched", None, {})])
        with env.begin() as conn:
            conn.execute(text("UPDATE ml_item_product_links SET match_status = 'conflict' WHERE item_id = 'MLA30'"))

        second = listing("unmatched", cursor=first["next_cursor"], limit=2)

        assert ids(second) == [("MLA40", 0), ("MLA50", 0)]

    @pytest.mark.parametrize("bad", ["", "nocolon", "MLA1:x", ":3", "MLA1:-1"])
    def test_a_malformed_cursor_is_refused(self, bad) -> None:
        with pytest.raises(ValueError):
            links.decode_cursor(bad)

    def test_the_cursor_round_trips(self) -> None:
        assert links.decode_cursor(links.encode_cursor("MLA123", 175550253195)) == ("MLA123", 175550253195)

    def test_the_page_size_is_bounded(self, env) -> None:
        seed(env, [(f"MLA{n:04d}", 0, "sku_auto", "unmatched", None, {}) for n in range(210)])
        assert len(listing("unmatched", limit=100000)["items"]) == links.LIST_MAX
