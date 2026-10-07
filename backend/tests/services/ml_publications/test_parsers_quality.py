"""Parsers and mappers of the quality sub-resources (competition, performance, moderation, visits),
over the real 2026-10-06 captures. A body that is not a capture is a deep copy of one with the named field changed."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.ml_publications.parsers.moderation import map_moderation, parse_moderation
from app.services.ml_publications.parsers.performance import map_performance, parse_performance
from app.services.ml_publications.parsers.price_to_win import map_price_to_win, parse_price_to_win
from app.services.ml_publications.parsers.subresource import MalformedSubResource
from app.services.ml_publications.parsers.visits import map_visits, parse_visits
from app.services.ml_publications.resources import RESOURCES
from tests.services.ml_publications.conftest import subresource_body, subresource_call

NOT_LISTED = "price_to_win_MLA874027718"
WINNING = "price_to_win_MLA882393030"


class TestPriceToWin:
    def test_200_is_ok_and_kept_unchanged(self):
        body = subresource_body("competition", WINNING)
        parsed = parse_price_to_win(200, body)
        assert (parsed.state, parsed.status, parsed.body, parsed.error_body) == ("ok", 200, body, None)

    def test_not_listed_maps_a_status_and_no_prices(self):
        typed = map_price_to_win(subresource_body("competition", NOT_LISTED))
        assert typed == {
            "status": "not_listed",
            "price_to_win": None,
            "current_price": None,
            "currency_id": None,
            "consistent": False,
        }

    def test_winning_maps_prices_as_exact_decimals(self):
        typed = map_price_to_win(subresource_body("competition", WINNING))
        assert typed == {
            "status": "winning",
            "price_to_win": Decimal("55882"),
            "current_price": Decimal("55882"),
            "currency_id": "ARS",
            "consistent": True,
        }

    def test_404_is_not_found_and_other_statuses_are_errors(self):
        assert parse_price_to_win(404, {"x": 1}).state == "not_found"
        assert parse_price_to_win(500, "boom").state == "error"

    @pytest.mark.parametrize("bad", [[], "x", {}, {"item_id": "MLA1"}])
    def test_200_without_a_status_is_malformed(self, bad):
        with pytest.raises(MalformedSubResource):
            parse_price_to_win(200, bad)


class TestPerformance:
    def test_200_user_product_body_maps_the_score(self):
        body = subresource_body("performance", "performance_MLA874027718")
        parsed = parse_performance(200, body)
        assert (parsed.state, parsed.body) == ("ok", body)
        assert map_performance(body) == {
            "applicable": True,
            "entity_type": "USER_PRODUCT",
            "entity_id": "MLAU245334053",
            "score": Decimal("66"),
            "level": "good",
            "calculated_at": datetime(2026, 10, 2, 19, 21, 54, 185000, tzinfo=timezone.utc),
        }

    def test_the_captured_product_items_400_is_a_state_not_an_error(self):
        call = subresource_call("performance", "performance_MLA882393030")
        parsed = parse_performance(call["status"], call["body"])
        assert (parsed.state, parsed.status, parsed.body) == ("ok", 400, call["body"])
        assert map_performance(call["body"]) == {
            "applicable": False,
            "entity_type": None,
            "entity_id": None,
            "score": None,
            "level": None,
            "calculated_at": None,
        }

    def test_any_other_400_stays_an_error_real_payload_one_field_changed(self):
        body = subresource_call("performance", "performance_MLA882393030")["body"]
        body["message"] = "Entity not calculated: something else"
        parsed = parse_performance(400, body)
        assert (parsed.state, parsed.error_body) == ("error", body)

    def test_404_is_not_found_and_5xx_is_an_error(self):
        assert parse_performance(404, {"x": 1}).state == "not_found"
        assert parse_performance(503, None).state == "error"

    def test_200_that_is_not_an_object_is_malformed(self):
        with pytest.raises(MalformedSubResource):
            parse_performance(200, [])

    def test_registry_declares_exactly_the_negative_state_the_parser_accepts(self):
        assert dict(RESOURCES["performance"].negative_states) == {400: "not_applicable"}


class TestModeration:
    def test_the_captured_404_is_the_no_moderation_state(self):
        call = subresource_call("moderation", "moderation_MLA874027718")
        parsed = parse_moderation(call["status"], call["body"])
        assert (parsed.state, parsed.status, parsed.body) == ("ok", 404, {"Status": 404})
        assert map_moderation(call["body"]) == {"has_moderation": False}

    def test_a_404_with_another_body_is_not_taken_for_no_moderation(self):
        """Synthetic transport fault (a gateway 404): only the captured body is the negative state."""
        parsed = parse_moderation(404, {"message": "route not found"})
        assert parsed.state == "not_found"

    def test_a_200_record_means_there_is_a_moderation(self):
        """No positive record was ever captured: any 200 object is `has_moderation = true` and nothing more."""
        parsed = parse_moderation(200, {"id": "M1"})
        assert parsed.state == "ok"
        assert map_moderation({"id": "M1"}) == {"has_moderation": True}

    def test_5xx_is_an_error_and_a_non_object_200_is_malformed(self):
        assert parse_moderation(500, None).state == "error"
        with pytest.raises(MalformedSubResource):
            parse_moderation(200, "x")

    def test_registry_declares_exactly_the_negative_state_the_parser_accepts(self):
        assert dict(RESOURCES["moderation"].negative_states) == {404: "no_moderation"}


class TestVisits:
    def test_200_with_results_maps_the_window(self):
        body = subresource_body("visits", "visits_MLA874027718")
        parsed = parse_visits(200, body)
        assert (parsed.state, parsed.body) == ("ok", body)
        assert map_visits(body) == {
            "window_days": 30,
            "total_visits": 13,
            "date_from": datetime(2026, 9, 6, tzinfo=timezone.utc),
            "date_to": datetime(2026, 10, 6, tzinfo=timezone.utc),
        }

    def test_200_without_visits_has_an_empty_results_list(self):
        body = subresource_body("visits", "visits_MLA903301838")
        assert parse_visits(200, body).state == "ok"
        assert map_visits(body)["total_visits"] == 0

    def test_results_are_keyed_by_date_in_the_registry(self):
        assert RESOURCES["visits"].array_keys == {"results": ("date",)}

    def test_404_is_not_found(self):
        assert parse_visits(404, {"message": "x"}).state == "not_found"

    @pytest.mark.parametrize("bad", [[], {"results": {}}, {"results": [{"total": 1}]}, {"results": [1]}])
    def test_a_results_entry_without_a_date_is_malformed(self, bad):
        with pytest.raises(MalformedSubResource):
            parse_visits(200, bad)
