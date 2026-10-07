"""`subresource_store.apply_subresource` for competition, performance, moderation and visits.

Postgres only. Every payload is a real capture; a transition is a deep copy of a real body with the one
labelled field changed (no losing competition sample and no moderation record exist yet).
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services.ml_publications.resources import RESOURCES
from app.services.ml_publications.settings_store import set_setting
from app.services.ml_publications.store import apply_fetch
from tests.services.ml_publications.conftest import sample_item, subresource_body, subresource_call
from tests.services.ml_publications.test_subresource_store import apply, events, logs

pytestmark = pytest.mark.postgres

T0 = datetime(2026, 10, 6, 13, 0, 0, tzinfo=timezone.utc)
CATALOG = "MLA882393030"  # active catalog listing of store 57997 (items sample)
PLAIN = "MLA874027718"
TABLES = {
    "competition": "ml_item_competition",
    "performance": "ml_item_performance",
    "moderation": "ml_item_moderations",
    "visits": "ml_item_visits",
}


def row_of(engine, resource: str, item_id: str = CATALOG):
    with engine.connect() as conn:
        return (
            conn.execute(text(f"SELECT * FROM {TABLES[resource]} WHERE item_id = :i"), {"i": item_id})
            .mappings()
            .first()
        )


def no_moderation() -> dict:
    return subresource_body("moderation", "moderation_MLA874027718")


def moderated() -> dict:
    """The captured no-moderation body with its only field changed (no record was ever captured)."""
    body = no_moderation()
    body["Status"] = 200
    return body


class TestModeration:
    def test_the_captured_404_is_a_state_not_gone_not_an_error(self, mlpub_pg) -> None:
        set_setting("events.enabled", True, "test")
        outcome = apply("moderation", CATALOG, no_moderation(), minutes=1, status=404)

        row = row_of(mlpub_pg, "moderation")
        assert outcome.kind == "first_seen" and outcome.change_log_id is None
        assert row["has_moderation"] is False and row["raw"] == {"Status": 404}
        assert row["http_status"] == 404 and row["gone_at"] is None and row["never_existed"] is False
        assert row["last_error"] is None and row["error_body"] is None
        assert logs(mlpub_pg) == [] and events(mlpub_pg) == []

    def test_a_repeated_404_changes_nothing_but_the_freshness(self, mlpub_pg) -> None:
        apply("moderation", CATALOG, no_moderation(), minutes=1, status=404)
        outcome = apply("moderation", CATALOG, no_moderation(), minutes=5, status=404)

        row = row_of(mlpub_pg, "moderation")
        assert outcome.kind == "unchanged" and logs(mlpub_pg) == []
        assert row["fetched_at"] == T0 + timedelta(minutes=1) and row["last_checked_at"] == T0 + timedelta(minutes=5)

    def test_a_record_then_back_to_404_is_applied_then_resolved(self, mlpub_pg) -> None:
        set_setting("events.enabled", True, "test")
        apply_fetch(RESOURCES["item"], (CATALOG,), _item_response(minutes=0))
        apply("moderation", CATALOG, no_moderation(), minutes=1, status=404)

        applied = apply("moderation", CATALOG, moderated(), minutes=2)
        resolved = apply("moderation", CATALOG, no_moderation(), minutes=3, status=404)

        assert (applied.kind, applied.events, resolved.kind, resolved.events) == ("changed", 1, "changed", 1)
        assert [(e["event_type"], e["old_value"], e["new_value"]) for e in events(mlpub_pg)] == [
            ("moderation_applied", "no_moderation", "moderation"),
            ("moderation_resolved", "moderation", "no_moderation"),
        ]
        assert {(e["official_store_id"], e["brand"]) for e in events(mlpub_pg)} == {(57997, "Marvo")}
        assert row_of(mlpub_pg, "moderation")["has_moderation"] is False

    def test_a_404_with_another_body_marks_the_item_gone_without_an_event(self, mlpub_pg) -> None:
        """Synthetic transport fault (a gateway 404): it is not the no-moderation state."""
        set_setting("events.enabled", True, "test")
        apply("moderation", CATALOG, no_moderation(), minutes=1, status=404)

        outcome = apply("moderation", CATALOG, {"message": "route not found"}, minutes=2, status=404)

        assert outcome.kind == "gone" and row_of(mlpub_pg, "moderation")["gone_at"] is not None
        assert events(mlpub_pg) == []


class TestPerformance:
    def test_the_200_body_is_stored_with_its_score(self, mlpub_pg) -> None:
        body = subresource_body("performance", "performance_MLA874027718")
        outcome = apply("performance", PLAIN, body, minutes=1)

        row = row_of(mlpub_pg, "performance", PLAIN)
        assert outcome.kind == "first_seen" and row["raw"] == body
        assert (row["applicable"], row["entity_type"], row["entity_id"]) == (True, "USER_PRODUCT", "MLAU245334053")
        assert (row["score"], row["level"]) == (Decimal("66.00"), "good")
        assert row["calculated_at"] == datetime(2026, 10, 2, 19, 21, 54, 185000, tzinfo=timezone.utc)

    def test_the_captured_product_items_400_is_not_applicable_and_not_an_error(self, mlpub_pg) -> None:
        call = subresource_call("performance", "performance_MLA882393030")
        outcome = apply("performance", CATALOG, call["body"], minutes=1, status=400)

        row = row_of(mlpub_pg, "performance")
        assert outcome.kind == "first_seen"
        assert row["applicable"] is False and row["raw"] == call["body"] and row["http_status"] == 400
        assert row["last_error"] is None and row["error_body"] is None and row["gone_at"] is None
        assert (row["score"], row["entity_id"]) == (None, None)

    def test_another_400_is_recorded_as_an_error_keeping_the_state(self, mlpub_pg) -> None:
        body = subresource_call("performance", "performance_MLA882393030")["body"]
        apply("performance", CATALOG, body, minutes=1, status=400)
        other = copy.deepcopy(body)
        other["message"] = "Entity not calculated: something else"

        outcome = apply("performance", CATALOG, other, minutes=2, status=400)

        row = row_of(mlpub_pg, "performance")
        assert outcome.kind == "error_recorded" and row["raw"] == body
        assert row["http_status"] == 400 and row["error_body"] == other and row["applicable"] is False


class TestCompetition:
    def test_not_listed_to_winning_stores_the_prices_and_raises_one_won_event(self, mlpub_pg) -> None:
        set_setting("events.enabled", True, "test")
        apply_fetch(RESOURCES["item"], (CATALOG,), _item_response(minutes=0))
        not_listed = subresource_body("competition", "price_to_win_MLA874027718")
        apply("competition", CATALOG, not_listed, minutes=1)

        first = row_of(mlpub_pg, "competition")
        assert (first["status"], first["price_to_win"], first["consistent"]) == ("not_listed", None, False)

        outcome = apply("competition", CATALOG, subresource_body("competition", "price_to_win_MLA882393030"), minutes=2)

        row = row_of(mlpub_pg, "competition")
        assert outcome.kind == "changed" and outcome.events == 1
        assert (row["status"], row["price_to_win"], row["currency_id"]) == ("winning", Decimal("55882.00"), "ARS")
        (event,) = events(mlpub_pg)
        assert (event["event_type"], event["old_value"], event["new_value"]) == (
            "catalog_competition_won",
            "not_listed",
            "winning",
        )
        assert event["payload"] == {"price_to_win": "55882", "current_price": "55882", "currency_id": "ARS"}
        assert (event["official_store_id"], event["brand"]) == (57997, "Marvo")

    def test_winning_to_another_status_raises_one_lost_event(self, mlpub_pg) -> None:
        """Real winning body, then the same body with `status` changed to `competing`."""
        set_setting("events.enabled", True, "test")
        winning = subresource_body("competition", "price_to_win_MLA882393030")
        losing = copy.deepcopy(winning)
        losing["status"] = "competing"
        apply("competition", CATALOG, winning, minutes=1)

        outcome = apply("competition", CATALOG, losing, minutes=2)

        assert outcome.events == 1
        assert [e["event_type"] for e in events(mlpub_pg)] == ["catalog_competition_lost"]
        assert logs(mlpub_pg, "competition")[0]["changed_paths"] == ["status"]


class TestVisits:
    def test_first_sighting_types_the_window(self, mlpub_pg) -> None:
        body = subresource_body("visits", "visits_MLA874027718")
        apply("visits", PLAIN, body, minutes=1)

        row = row_of(mlpub_pg, "visits", PLAIN)
        assert (row["window_days"], row["total_visits"]) == (30, 13)
        assert row["date_from"] == datetime(2026, 9, 6, tzinfo=timezone.utc)
        assert len(row["raw"]["results"]) == 11

    def test_a_refetch_with_one_more_day_logs_only_that_day_never_the_whole_window(self, mlpub_pg) -> None:
        """Real visits capture as the old side; the new side is the capture itself, so the old side lacks the
        last day of `results` (real payload, one day removed)."""
        new = subresource_body("visits", "visits_MLA874027718")
        old = copy.deepcopy(new)
        added = old["results"].pop()
        apply("visits", PLAIN, old, minutes=1)

        outcome = apply("visits", PLAIN, new, minutes=2)

        (entry,) = logs(mlpub_pg, "visits")
        assert outcome.kind == "changed"
        assert entry["changed_paths"] == [f"results[{added['date']}]"]
        assert len(str(entry["changes"])) < len(str(new)) / 4  # a day's entry, not a copy of the 30-day window

    def test_an_identical_refetch_is_unchanged_and_an_empty_window_is_a_valid_state(self, mlpub_pg) -> None:
        empty = subresource_body("visits", "visits_MLA903301838")
        apply("visits", PLAIN, empty, minutes=1)
        outcome = apply("visits", PLAIN, empty, minutes=2)

        assert outcome.kind == "unchanged" and logs(mlpub_pg) == []
        assert row_of(mlpub_pg, "visits", PLAIN)["total_visits"] == 0


def _item_response(minutes: float):
    from tests.services.ml_publications.test_subresource_store import response

    return response("item", sample_item(CATALOG), minutes=minutes)
