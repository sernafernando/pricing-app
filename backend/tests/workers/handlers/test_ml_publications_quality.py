"""The refresh handler's competition, moderation, performance and visits fetchers (design D12, D16).

Postgres only. The core is the real `/items/bulk` capture (MLA934406852 is a catalog listing, MLA935110613 is
not); every sub-resource body is a real capture served for whatever item is asked (rows are keyed by the
REQUESTED id). A state the captures lack (an item under review) is a real element with one labelled field
changed; transport faults are labelled synthetic.
"""

from __future__ import annotations

import copy
import re

import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.services.ml_publications.conftest import subresource_body, subresource_call
from tests.workers.handlers.test_ml_publications_bundle_policy import paths
from tests.workers.handlers.test_ml_publications_refresh import (
    NoCallTransport,
    ScriptedTransport,
    bulk_answer,
    bulk_responder,
    context,
    counters_of,
    enable_refresh,
    enqueue_items,
    json_response,
    queue_row,
    make_handler,
    sql_all,
    sql_scalar,
)

pytestmark = pytest.mark.postgres

CATALOG = "MLA934406852"  # catalog_listing true
PLAIN = "MLA935110613"  # catalog_listing false, paused / out_of_stock
PATH = re.compile(
    r"^/(items/(?P<a>[^/]+)/(price_to_win|visits/time_window)|moderations/last_moderation/(?P<b>[^/]+)-ITM"
    r"|item/(?P<c>[^/]+)/performance)$"
)
PRICE_TO_WIN = subresource_body("competition", "price_to_win_MLA882393030")
NO_MODERATION = subresource_body("moderation", "moderation_MLA874027718")
PERFORMANCE = subresource_body("performance", "performance_MLA874027718")
PERFORMANCE_REFUSED = subresource_call("performance", "performance_MLA882393030")["body"]
VISITS = subresource_body("visits", "visits_MLA874027718")


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
    with mlpub_pg.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE worker_job_state (name varchar(64) PRIMARY KEY, last_run_at timestamptz, "
                "last_success_at timestamptz, state varchar(32), detail jsonb, heartbeat_at timestamptz)"
            )
        )
    monkeypatch.setattr(settings, "ML_USER_ID", "1")
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "1")
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    return mlpub_pg


def responder_for(*, under_review: bool = False, moderation=None, performance=None):
    """Bulk (optionally with the items' status changed to `under_review`: real element, one field changed) and
    the captured body of each quality endpoint, or the ready response given for moderation / performance."""

    def responder(request, call):
        if request.url.path == "/items/bulk":
            if not under_review:
                return bulk_responder(request, call)
            answer = bulk_answer(request.url.params["ids"].split(","))
            for element in answer:
                if element["status_code"] == 200:
                    element["body"]["status"] = "under_review"
            return json_response(answer)
        path = request.url.path
        assert PATH.match(path), f"unexpected path {path}"
        if "price_to_win" in path:
            return json_response(copy.deepcopy(PRICE_TO_WIN))
        if "last_moderation" in path:
            return moderation or json_response(copy.deepcopy(NO_MODERATION), status=404)
        if path.endswith("/performance"):
            return performance or json_response(copy.deepcopy(PERFORMANCE))
        return json_response(copy.deepcopy(VISITS))

    return responder


def one(engine, table: str, item: str):
    rows = sql_all(engine, f"SELECT * FROM {table} WHERE item_id = :i", i=item)
    return rows[0] if rows else None


class TestCompetition:
    def test_a_catalog_listing_is_asked_with_version_v2_and_stored(self, env) -> None:
        enable_refresh(bundle_resources=["core", "competition"])
        enqueue_items(CATALOG)
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk", f"/items/{CATALOG}/price_to_win"]
        assert dict(transport.requests[-1].url.params) == {"version": "v2"}
        row = one(env, "ml_item_competition", CATALOG)
        assert (row["status"], row["http_status"], row["raw"]) == ("winning", 200, PRICE_TO_WIN)
        assert queue_row(env, CATALOG) is None

    def test_an_item_that_is_not_a_catalog_listing_gets_no_request_and_no_row(self, env) -> None:
        enable_refresh(bundle_resources=["core", "competition"])
        enqueue_items(PLAIN)
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert sql_scalar(env, "SELECT count(*) FROM ml_item_competition") == 0
        assert counters_of(env)["skipped_not_applicable"] == {"competition": 1}
        assert queue_row(env, PLAIN) is None  # settled uncharged

    def test_naming_competition_for_a_non_catalog_item_does_not_request_it_either(self, env) -> None:
        enable_refresh(bundle_resources=["core", "competition"])
        enqueue_items(PLAIN)
        make_handler(ScriptedTransport(responder_for())).run(context())  # the core is now stored

        enqueue_items(PLAIN, resources=("competition",))
        make_handler(NoCallTransport()).run(context())

        assert sql_scalar(env, "SELECT count(*) FROM ml_item_competition") == 0
        assert queue_row(env, PLAIN) is None

    def test_a_named_competition_for_an_item_not_in_the_store_is_requeued_with_its_core_not_lost(self, env) -> None:
        """The catalog notification can arrive before the item is stored: its core goes first, then competition."""
        enable_refresh(bundle_resources=["core", "competition"])
        enqueue_items(CATALOG, resources=("competition",))
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        # Whether the item is a catalog listing was unknown, so nothing was asked for it first: the entry was
        # refetched in the same run, core before competition.
        assert paths(transport) == ["/items/bulk", f"/items/{CATALOG}/price_to_win"]
        assert counters_of(env)["requeued_for_core"] == {"competition": 1}
        assert one(env, "ml_item_competition", CATALOG)["status"] == "winning"
        assert queue_row(env, CATALOG) is None

    def test_the_other_resources_of_a_requeued_entry_are_fetched_once_not_twice(self, env) -> None:
        enable_refresh(bundle_resources=["core", "competition", "moderation"])
        enqueue_items(CATALOG, resources=("competition", "moderation"))
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert sorted(paths(transport)) == sorted(
            ["/items/bulk", f"/items/{CATALOG}/price_to_win", f"/moderations/last_moderation/{CATALOG}-ITM"]
        )
        assert queue_row(env, CATALOG) is None

    def test_the_requeued_core_of_a_non_catalog_item_ends_the_entry_without_a_competition_row(self, env) -> None:
        enable_refresh(bundle_resources=["core", "competition"])
        enqueue_items(PLAIN, resources=("competition",))
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert sql_scalar(env, "SELECT count(*) FROM ml_item_competition") == 0
        assert queue_row(env, PLAIN) is None  # no loop: the item is stored now and does not qualify
        counters = counters_of(env)
        assert (counters["requeued_for_core"], counters["skipped_not_applicable"]) == (
            {"competition": 1},
            {"competition": 1},
        )

    def test_a_named_competition_whose_core_is_gone_ends_without_a_loop(self, env) -> None:
        enable_refresh(bundle_resources=["core", "competition"])
        enqueue_items("MLA1", resources=("competition",))  # the captured item that does not exist
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert queue_row(env, "MLA1") is None and sql_scalar(env, "SELECT count(*) FROM ml_item_competition") == 0

    def test_the_bundle_waits_15_minutes_between_fetches_and_a_named_entry_does_not(self, env) -> None:
        enable_refresh(bundle_resources=["core", "competition"])
        enqueue_items(CATALOG)
        make_handler(ScriptedTransport(responder_for())).run(context())

        enqueue_items(CATALOG)
        recent = ScriptedTransport(responder_for())
        make_handler(recent).run(context())
        assert paths(recent) == ["/items/bulk"] and counters_of(env)["skipped_min_age"] == {"competition": 1}

        enqueue_items(CATALOG, resources=("competition",))
        named = ScriptedTransport(responder_for())
        make_handler(named).run(context())
        assert paths(named) == [f"/items/{CATALOG}/price_to_win"]


class TestModeration:
    def test_a_paused_item_without_a_moderation_signal_is_not_asked_on_the_bundle(self, env) -> None:
        enable_refresh(bundle_resources=["core", "moderation"])
        enqueue_items(PLAIN)
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert counters_of(env)["skipped_not_applicable"] == {"moderation": 1}

    def test_an_item_under_review_is_asked_and_the_404_is_a_state_that_completes_the_entry(self, env) -> None:
        enable_refresh(bundle_resources=["core", "moderation"])
        enqueue_items(PLAIN)
        transport = ScriptedTransport(responder_for(under_review=True))

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk", f"/moderations/last_moderation/{PLAIN}-ITM"]
        row = one(env, "ml_item_moderations", PLAIN)
        assert (row["has_moderation"], row["http_status"], row["gone_at"], row["raw"]) == (
            False,
            404,
            None,
            NO_MODERATION,
        )
        assert queue_row(env, PLAIN) is None
        assert counters_of(env)["subresources"]["moderation"] == {"first_seen": 1}
        assert sql_scalar(env, "SELECT count(*) FROM ml_item_events") == 0

    def test_a_named_moderation_entry_is_asked_for_any_item(self, env) -> None:
        enable_refresh(bundle_resources=["core", "moderation"])
        enqueue_items(PLAIN, resources=("moderation",))
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == [f"/moderations/last_moderation/{PLAIN}-ITM"]
        assert one(env, "ml_item_moderations", PLAIN)["has_moderation"] is False

    def test_a_moderation_that_appears_and_then_resolves_raises_both_events(self, env) -> None:
        """No record was captured: the 200 is the captured 404 body with its one field changed."""
        enable_refresh(bundle_resources=["core", "moderation"], events__enabled=True)
        record = copy.deepcopy(NO_MODERATION)
        record["Status"] = 200
        for answer in (None, json_response(record), None):
            enqueue_items(PLAIN, resources=("moderation",))
            make_handler(ScriptedTransport(responder_for(moderation=answer))).run(context())

        assert [e["event_type"] for e in sql_all(env, "SELECT event_type FROM ml_item_events ORDER BY id")] == [
            "moderation_applied",
            "moderation_resolved",
        ]


class TestSweepOnlyResources:
    def test_the_bundle_never_fetches_performance_or_visits_even_when_enabled(self, env) -> None:
        enable_refresh(bundle_resources=["core", "performance", "visits"])
        enqueue_items(CATALOG)
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert counters_of(env)["skipped_disabled"] == {"performance": 1, "visits": 1}
        assert queue_row(env, CATALOG) is None

    def test_a_named_performance_entry_is_fetched_and_stored(self, env) -> None:
        enable_refresh(bundle_resources=["core", "performance"])
        enqueue_items(CATALOG, resources=("performance",))
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == [f"/item/{CATALOG}/performance"]
        row = one(env, "ml_item_performance", CATALOG)
        assert (row["applicable"], row["entity_id"], row["level"]) == (True, "MLAU245334053", "good")
        assert queue_row(env, CATALOG) is None

    def test_the_product_items_400_completes_the_entry_without_a_charged_attempt(self, env) -> None:
        enable_refresh(bundle_resources=["core", "performance"])
        enqueue_items(CATALOG, resources=("performance",))
        refused = json_response(copy.deepcopy(PERFORMANCE_REFUSED), status=400)

        make_handler(ScriptedTransport(responder_for(performance=refused))).run(context())

        row = one(env, "ml_item_performance", CATALOG)
        assert (row["applicable"], row["http_status"], row["last_error"]) == (False, 400, None)
        assert queue_row(env, CATALOG) is None  # completed, not parked, not retried
        assert counters_of(env)["subresources"]["performance"] == {"first_seen": 1}

    def test_any_other_400_is_a_failure_charged_to_performance_alone(self, env) -> None:
        """Synthetic fault: a 400 that is not the captured product-items refusal."""
        enable_refresh(bundle_resources=["core", "performance"])
        enqueue_items(CATALOG, resources=("performance",))
        other = copy.deepcopy(PERFORMANCE_REFUSED)
        other["message"] = "Invalid entity"

        make_handler(ScriptedTransport(responder_for(performance=json_response(other, status=400)))).run(context())

        queued = queue_row(env, CATALOG)
        assert queued["resources"] == ["performance"] and queued["attempts"] == 1
        assert "performance: HTTP 400" in queued["last_error"]

    def test_a_named_visits_entry_asks_for_30_days_and_stores_the_window(self, env) -> None:
        enable_refresh(bundle_resources=["core", "visits"])
        enqueue_items(CATALOG, resources=("visits",))
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == [f"/items/{CATALOG}/visits/time_window"]
        assert dict(transport.requests[0].url.params) == {"last": "30", "unit": "day"}
        row = one(env, "ml_item_visits", CATALOG)
        assert (row["window_days"], row["total_visits"]) == (30, 13)
