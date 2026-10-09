"""P8b.T1 (pure part): the history's business/technical split, the event labels and the exported event types.

No database. Every change list is the REAL diff between a captured body and a deep copy of it with the named field
changed (the way the store logs it, see `test_events.py`), so the paths the allowlist matches are the paths the
store writes, not paths made up for the test.
"""

from __future__ import annotations

import ast
import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.ml_publications import events as events_module
from app.services.ml_publications.diff import diff, split_excluded
from app.services.ml_publications.resources import RESOURCES
from app.services.ml_publications.view import events_view, filters, history
from tests.services.ml_publications.conftest import sample_item, subresource_body

ACTIVE = "MLA874027718"


def changes_of(resource: str, old: dict, new: dict) -> list[dict]:
    reportable, _ = split_excluded(diff(old, new, RESOURCES[resource]), resource)
    return [c.as_dict() for c in reportable]


def paths(lines: list[history.Change]) -> list[str]:
    return [line.path for line in lines]


class TestSplit:
    def test_the_price_is_business_and_the_health_is_technical(self) -> None:
        """real active item with `price` and `health` changed."""
        old = sample_item(ACTIVE)
        new = copy.deepcopy(old)
        new["price"], new["health"] = old["price"] + 100, 0.1
        business, technical = history.split("item", changes_of("item", old, new))
        assert paths(business) == ["price"] and paths(technical) == ["health"]
        (price,) = business
        assert (price.old, price.new) == (old["price"], old["price"] + 100)
        assert price.label_key == "price" and price.label == "Precio"

    def test_one_line_per_field_in_the_order_of_the_change_log(self) -> None:
        """real active item with status, available_quantity and title changed in one row (S58.3)."""
        old = sample_item(ACTIVE)
        new = copy.deepcopy(old)
        new["status"], new["available_quantity"], new["title"] = "paused", 0, "Otro titulo"
        stored = changes_of("item", old, new)
        business, technical = history.split("item", stored)
        assert paths(business) == [c["p"] for c in stored] and technical == []
        assert {line.path: (line.old, line.new) for line in business} == {
            "status": ("active", "paused"),
            "available_quantity": (old["available_quantity"], 0),
            "title": (old["title"], "Otro titulo"),
        }

    @pytest.mark.parametrize(
        "field, value, path, label_key",
        [
            ("base_price", 1.0, "base_price", "base_price"),
            ("original_price", 5.0, "original_price", "original_price"),
            ("listing_type_id", "gold_pro", "listing_type_id", "listing_type"),
            ("catalog_listing", True, "catalog_listing", "catalog_listing"),
        ],
    )
    def test_the_top_level_business_fields(self, field, value, path, label_key) -> None:
        old = sample_item(ACTIVE)
        new = copy.deepcopy(old)
        new[field] = value
        business, technical = history.split("item", changes_of("item", old, new))
        assert paths(business) == [path] and technical == []
        assert business[0].label_key == label_key and business[0].label

    def test_the_logistic_type_and_the_set_members_are_business(self) -> None:
        """real active item with its logistic type changed, a tag added and a sub status set."""
        old = sample_item(ACTIVE)
        new = copy.deepcopy(old)
        new["shipping"]["logistic_type"] = (
            "cross_docking" if old["shipping"]["logistic_type"] != "cross_docking" else "x"
        )
        new["tags"] = [*old["tags"], "poor_quality_thumbnail"]
        new["sub_status"] = ["out_of_stock"]
        business, technical = history.split("item", changes_of("item", old, new))
        assert set(paths(business)) == {
            "shipping.logistic_type",
            "tags[=poor_quality_thumbnail]",
            "sub_status[=out_of_stock]",
        }
        assert technical == []

    def test_only_the_installments_campaign_of_the_sale_terms_is_business(self) -> None:
        old = sample_item(ACTIVE)
        new = copy.deepcopy(old)
        new["sale_terms"] = [
            {**term, "value_name": "zz"} for term in old["sale_terms"] if term["id"] in ("INVOICE", "WARRANTY_TYPE")
        ]
        campaign = {"id": "INSTALLMENTS_CAMPAIGN", "name": "Campana", "value_name": "9x_campaign"}
        new["sale_terms"].append(campaign)
        business, technical = history.split("item", changes_of("item", old, new))
        assert paths(business) == ["sale_terms[INSTALLMENTS_CAMPAIGN]"]
        assert business[0].label_key == "installments_campaign" and business[0].old is None
        assert all(p.startswith("sale_terms[") for p in paths(technical)) and technical

    def test_an_added_field_has_no_old_value(self) -> None:
        old = sample_item(ACTIVE)
        new = copy.deepcopy(old)
        del old["original_price"]
        new["original_price"] = 99.0
        (line,) = history.split("item", changes_of("item", old, new))[0]
        assert (line.path, line.old, line.new) == ("original_price", None, 99.0)

    def test_the_price_list_amounts_of_the_prices_resource(self) -> None:
        """real prices body (one standard price) with its amount changed."""
        old = subresource_body("prices", "prices_MLA903301838")
        new = copy.deepcopy(old)
        new["prices"][0]["amount"] = 20000.0
        new["prices"][0]["last_updated"] = "2026-10-09T00:00:00Z"
        business, technical = history.split("prices", changes_of("prices", old, new))
        assert paths(business) == ["prices[339].amount"] and paths(technical) == ["prices[339].last_updated"]

    def test_the_sale_price_amount_and_promotion_type(self) -> None:
        """real sale price with a promotion in force, its amount and promotion type changed."""
        old = subresource_body("sale_price", "sale_price_started_MLA2146576013")
        new = copy.deepcopy(old)
        new["amount"], new["metadata"]["promotion_type"] = 1.0, "lightning"
        new["price_id"] = "9"
        business, technical = history.split("sale_price", changes_of("sale_price", old, new))
        assert set(paths(business)) == {"amount", "metadata.promotion_type"}
        assert paths(technical) == ["price_id"]

    def test_the_quantity_of_a_stock_location(self) -> None:
        """real user product stock with the Full quantity changed."""
        old = subresource_body("stock", "user_product_stock_MLAU245334053")
        new = copy.deepcopy(old)
        new["locations"][1]["quantity"] = 7
        new["last_updated"] = "2026-10-09T00:00:00Z"
        business, technical = history.split("stock", changes_of("stock", old, new))
        assert paths(business) == ["locations[meli_facility].quantity"]
        assert business[0].label_key == "stock_location" and (business[0].old, business[0].new) == (0, 7)
        assert paths(technical) == ["last_updated"]

    def test_a_promotion_that_starts_and_one_that_appears(self) -> None:
        """real promotions list with the started campaign finished, and a PRICE_DISCOUNT dropped."""
        old = subresource_body("promotions", "promotions_started_MLA2146576013")
        new = copy.deepcopy(old)
        started = next(p for p in new if p["id"] == "C-MLA1669550")
        started["status"], started["price"] = "finished", 1400000
        dropped = next(p for p in new if p["type"] == "PRICE_DISCOUNT")
        new.remove(dropped)
        business, _ = history.split("promotions", changes_of("promotions", old, new))
        assert "[C-MLA1669550].status" in paths(business) and "[C-MLA1669550].price" in paths(business)
        assert any(line.label_key == "promotion" for line in business)  # the vanished entry

    def test_the_catalog_competition_status(self) -> None:
        """real price-to-win with its status changed."""
        old = subresource_body("competition", "price_to_win_MLA882393030")
        new = copy.deepcopy(old)
        new["status"], new["visit_share"] = "competing", "medium"
        business, technical = history.split("competition", changes_of("competition", old, new))
        assert paths(business) == ["status"] and paths(technical) == ["visit_share"]

    def test_the_product_link_change(self) -> None:
        """the row `links.py` writes (its `LOGGED_FIELDS` as `replace` changes)."""
        stored = [
            {"p": "producto_item_id", "op": "replace", "old": 70, "new": 71},
            {"p": "source", "op": "replace", "old": "sku_auto", "new": "manual"},
        ]
        business, technical = history.split("product_link", stored)
        assert paths(business) == ["producto_item_id"] and paths(technical) == ["source"]
        assert business[0].label_key == "product_link"

    def test_a_resource_outside_the_allowlist_is_all_technical(self) -> None:
        stored = [{"p": "price", "op": "replace", "old": 1, "new": 2}]
        business, technical = history.split("visits", stored)
        assert business == [] and paths(technical) == ["price"]  # the same path means price only on the item

    def test_a_technical_line_has_no_label(self) -> None:
        old = sample_item(ACTIVE)
        new = copy.deepcopy(old)
        new["health"] = 0.1
        (line,) = history.split("item", changes_of("item", old, new))[1]
        assert line.label_key is None and line.label is None

    def test_no_changes_gives_two_empty_lists(self) -> None:
        assert history.split("item", []) == ([], [])


class TestEventTypes:
    def test_the_exported_list_is_what_the_rules_can_emit(self) -> None:
        """Every event type literal in `events.py` (an `Event(...)`, a `_promotion_event(...)`, a `_field_event(...)`,
        an `event_type = ...` or the status table) is in `EVENT_TYPES`, and nothing else is."""
        tree = ast.parse(Path(events_module.__file__).read_text(encoding="utf-8"))
        found: set[str] = set()
        constants = {
            node.targets[0].id: node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }

        def literal(node: ast.AST) -> None:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.add(node.value)
            elif isinstance(node, ast.Name) and node.id in constants:
                found.add(constants[node.id])

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("Event", "_promotion_event") and node.args:
                    literal(node.args[0])
                elif node.func.id == "_field_event" and len(node.args) > 1:
                    literal(node.args[1])
            elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == "event_type":
                    literal(node.value)
                elif node.targets[0].id == "STATUS_EVENT_BY_VALUE" and isinstance(node.value, ast.Dict):
                    for value in node.value.values:
                        literal(value)
        found.add(events_module.STATUS_EVENT_OTHER)
        found.add(events_module.PRICE_CHANGED)
        assert found == set(events_module.EVENT_TYPES)

    def test_the_list_has_no_repeats_and_is_a_tuple(self) -> None:
        assert isinstance(events_module.EVENT_TYPES, tuple)
        assert len(set(events_module.EVENT_TYPES)) == len(events_module.EVENT_TYPES) == 22

    def test_the_filter_vocabulary_only_holds_real_types(self) -> None:
        assert filters.EVENT_TYPES <= set(events_module.EVENT_TYPES)


class TestLabels:
    @pytest.mark.parametrize("event_type", events_module.EVENT_TYPES)
    def test_every_real_type_has_its_own_spanish_label(self, event_type: str) -> None:
        label = events_view.label_of(event_type)
        assert event_type in events_view.EVENT_LABELS and label != events_view.GENERIC_LABEL

    def test_the_label_table_has_no_extra_types(self) -> None:
        assert set(events_view.EVENT_LABELS) == set(events_module.EVENT_TYPES)

    def test_an_unmapped_type_gets_the_generic_label(self) -> None:
        assert events_view.label_of("something_new") == events_view.GENERIC_LABEL == "Evento"

    def test_there_are_no_derived_events(self) -> None:
        assert not {"sale_recorded", "negative_margin", "venta_registrada", "margen_negativo"} & set(
            events_view.EVENT_LABELS
        )


class TestCursor:
    def test_it_round_trips_with_microseconds_and_no_plus_sign(self) -> None:
        at = datetime(2026, 10, 8, 12, 0, 1, 123456, tzinfo=timezone.utc)
        token = events_view.encode_cursor(at, 42)
        assert "+" not in token and token.endswith("|42")
        assert events_view.decode_cursor(token) == (at, 42)

    @pytest.mark.parametrize(
        "token", ["", "x", "2026-10-08|1", "2026-10-08T12:00:00Z|x", "|1", "a|b|c", "2026-10-08T12:00:00Z|-1"]
    )
    def test_a_malformed_token_is_a_cursor_error(self, token: str) -> None:
        with pytest.raises(filters.FilterError) as caught:
            events_view.decode_cursor(token)
        assert caught.value.field == "cursor"
