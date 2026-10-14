"""Sub-resource answers production recorded as errors that are states of the item (captured 2026-10-14).

Every body comes from `subresource_states_20261014.json`, copied unchanged from the prod rows that held them
as errors. Recorded as errors, they charged the queue entry one attempt per fetch until it parked (8.5k items
parked from 2026-10-09). Each one is a fact about the item, so it is stored as a state and settles the entry.
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import text

from app.services.ml_publications.events import derive_events
from app.services.ml_publications.parsers.moderation import map_moderation, parse_moderation
from app.services.ml_publications.parsers.performance import map_performance, parse_performance
from app.services.ml_publications.parsers.seller_promotions import map_seller_promotions, parse_seller_promotions
from app.services.ml_publications.parsers.subresource import MalformedSubResource
from app.services.ml_publications.resources import RESOURCES
from tests.services.ml_publications.conftest import load_fixture, subresource_body
from tests.services.ml_publications.test_events_quality import row_of
from tests.services.ml_publications.test_subresource_store import apply

PROD_STATES = "subresource_states_20261014.json"


def calls(resource: str, status: int | None = None) -> list[dict]:
    found = [
        copy.deepcopy(c)
        for c in load_fixture(PROD_STATES)["calls"]
        if c["resource"] == resource and (status is None or c["status"] == status)
    ]
    assert found, (resource, status)
    return found


def call(name: str) -> dict:
    return next(copy.deepcopy(c) for c in load_fixture(PROD_STATES)["calls"] if c["name"] == name)


MODERATION_LIST = "moderation_MLA1508345743_200"
MODERATION_EMPTY = "moderation_MLA2461088796_204"


class TestPerformanceNotCalculated:
    @pytest.mark.parametrize("captured", calls("performance"), ids=lambda c: c["name"])
    def test_a_captured_not_calculated_400_is_the_not_applicable_state(self, captured):
        parsed = parse_performance(captured["status"], captured["body"])
        assert (parsed.state, parsed.status, parsed.body) == ("ok", 400, captured["body"])
        assert map_performance(parsed.body) == {
            "applicable": False,
            "entity_type": None,
            "entity_id": None,
            "score": None,
            "level": None,
            "calculated_at": None,
        }

    def test_the_reason_stays_in_the_stored_body(self):
        body = call("performance_MLA1100694747_400")["body"]
        assert parse_performance(400, body).body["message"] == "Entity not calculated: Only status active is supported"

    def test_an_unknown_not_calculated_reason_stays_an_error_real_payload_one_field_changed(self):
        body = call("performance_MLA1100694747_400")["body"]
        body["message"] = "Entity not calculated: something else"
        parsed = parse_performance(400, body)
        assert (parsed.state, parsed.error_body) == ("error", body)


class TestModerationRecords:
    def test_a_200_list_of_records_is_a_moderation(self):
        captured = call(MODERATION_LIST)
        parsed = parse_moderation(200, captured["body"])
        assert (parsed.state, parsed.body) == ("ok", captured["body"])
        assert map_moderation(parsed.body) == {"has_moderation": True}

    def test_a_204_without_body_is_no_moderation_stored_as_an_empty_record_list(self):
        captured = call(MODERATION_EMPTY)
        assert captured["body"] is None
        parsed = parse_moderation(204, captured["body"])
        assert (parsed.state, parsed.status, parsed.body) == ("ok", 204, [])
        assert map_moderation(parsed.body) == {"has_moderation": False}

    @pytest.mark.parametrize("bad", [[1], [{"id": "1"}, "x"], "x"])
    def test_a_list_holding_something_other_than_records_is_malformed(self, bad):
        with pytest.raises(MalformedSubResource):
            parse_moderation(200, bad)

    def test_a_204_with_a_body_is_malformed(self):
        with pytest.raises(MalformedSubResource):
            parse_moderation(204, call(MODERATION_LIST)["body"])

    def test_records_after_the_no_moderation_404_is_one_applied_event(self):
        old = subresource_body("moderation", "moderation_MLA874027718")
        events = derive_events(row_of("moderation", old, call(MODERATION_LIST)["body"]))
        assert [(e.event_type, e.old_value, e.new_value) for e in events] == [
            ("moderation_applied", "no_moderation", "moderation")
        ]

    def test_records_going_away_with_a_204_is_one_resolved_event(self):
        new = parse_moderation(204, None).body
        events = derive_events(row_of("moderation", call(MODERATION_LIST)["body"], new))
        assert [(e.event_type, e.old_value, e.new_value) for e in events] == [
            ("moderation_resolved", "moderation", "no_moderation")
        ]

    def test_another_record_list_raises_no_event(self):
        other = call("moderation_MLA2125544731_200")["body"]
        assert derive_events(row_of("moderation", call(MODERATION_LIST)["body"], other)) == []


class TestPromotionsNotEligible:
    @pytest.mark.parametrize("captured", calls("promotions"), ids=lambda c: c["name"])
    def test_a_captured_not_eligible_400_is_a_state_with_no_promotions(self, captured):
        parsed = parse_seller_promotions(captured["status"], captured["body"])
        assert (parsed.state, parsed.status, parsed.body) == ("ok", 400, captured["body"])
        assert map_seller_promotions(parsed.body) == {
            "candidate_count": 0,
            "started_count": 0,
            "started_promotion_keys": [],
        }

    @pytest.mark.parametrize(
        "message", ["Item status is not allowed", "Item status is not allowed (active", "something else"]
    )
    def test_any_other_400_stays_an_error_real_payload_one_field_changed(self, message):
        body = call("promotions_MLA1528343333_400")["body"]
        body["message"] = message
        parsed = parse_seller_promotions(400, body)
        assert (parsed.state, parsed.error_body) == ("error", body)

    def test_not_eligible_raises_no_promotion_event(self):
        started = subresource_body("promotions", "promotions_started_MLA2146576013")
        not_eligible = call("promotions_MLA1528343333_400")["body"]
        assert derive_events(row_of("promotions", started, not_eligible)) == []

    def test_registry_declares_the_negative_state(self):
        assert dict(RESOURCES["promotions"].negative_states) == {400: "not_eligible"}


@pytest.mark.postgres
class TestStoredAsStates:
    """Through the store: a captured answer is a state row (no error recorded), so the refresh is not charged."""

    TABLES = {
        "performance": "ml_item_performance",
        "moderation": "ml_item_moderations",
        "promotions": "ml_item_seller_promotions",
    }

    @pytest.mark.parametrize("captured", load_fixture(PROD_STATES)["calls"], ids=lambda c: c["name"])
    def test_every_captured_answer_is_stored_as_a_state(self, mlpub_pg, captured):
        outcome = apply(captured["resource"], captured["item_id"], captured["body"], status=captured["status"])

        assert outcome.kind == "first_seen"
        with mlpub_pg.connect() as conn:
            stored = (
                conn.execute(
                    text(f"SELECT * FROM {self.TABLES[captured['resource']]} WHERE item_id = :i"),
                    {"i": captured["item_id"]},
                )
                .mappings()
                .one()
            )
        assert stored["raw"] == ([] if captured["status"] == 204 else captured["body"])
        assert (stored["http_status"], stored["error_body"], stored["last_error"]) == (captured["status"], None, None)
