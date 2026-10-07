"""The refresh handler's promotions fetcher (design D14): `/seller-promotions/items/{id}?app_version=v2`
behind two gates (`promotions.enabled` AND `promotions` in `bundle_resources`), the 300 s minimum age,
the store with its events, and the bridge promotion mirror left alone.

Postgres only. Bodies are the real captures of `/seller-promotions/items/{id}` (2026-10-06) served for
whatever item is asked (rows are keyed by the REQUESTED id). A test that needs a transition labels the
one change it makes to a deep copy of a real body; transport faults (500) are labelled synthetic.
"""

from __future__ import annotations

import copy
import re

import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.services.ml_publications.conftest import subresource_body, subresource_call
from tests.workers.handlers.test_ml_publications_bundle_policy import (
    paths,
    queue_row,
    release_backoff,
    sub_row,
)
from tests.workers.handlers.test_ml_publications_refresh import (
    NoCallTransport,
    ScriptedTransport,
    bulk_responder,
    context,
    counters_of,
    enable_refresh,
    enqueue_items,
    json_response,
    make_handler,
    sql_all,
    sql_scalar,
)

pytestmark = pytest.mark.postgres

ITEM = "MLA935110613"
PROMOTIONS_PATH = re.compile(r"^/seller-promotions/items/(?P<item>[^/]+)$")
STARTED = subresource_body("promotions", "promotions_started_MLA2146576013")  # 1 started + 6 candidates
CANDIDATES = subresource_body("promotions", "promotions_MLA874027718")  # 8 candidates, none started
NOT_FOUND = subresource_call("promotions", "promotions_unknown")
CAMPAIGN = "C-MLA1664342"
ENABLED = {"bundle_resources": ["core", "promotions"], "promotions__enabled": True}
TABLE = "ml_item_seller_promotions"


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
    """The real core and sub-resource schema plus `worker_job_state`, with ML credentials configured."""
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


def responder_for(body=None, *, response=None):
    """Bulk for `/items/bulk`, the given promotions list (or ready response) for the promotions path."""
    served = STARTED if body is None else body

    def responder(request, call):
        if request.url.path == "/items/bulk":
            return bulk_responder(request, call)
        assert PROMOTIONS_PATH.match(request.url.path), f"unexpected path {request.url.path}"
        return response if response is not None else json_response(copy.deepcopy(served))

    return responder


def started_campaign(price: int = 1900000) -> list:
    """Real candidates-only list with the campaign C-MLA1664342 started (status and price changed)."""
    body = copy.deepcopy(CANDIDATES)
    entry = next(e for e in body if e.get("id") == CAMPAIGN)
    entry.update(status="started", price=price)
    return body


class TestTheTwoGates:
    def test_with_both_flags_the_promotions_are_fetched_after_the_core_and_stored(self, env) -> None:
        enable_refresh(**ENABLED)
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk", f"/seller-promotions/items/{ITEM}"]
        request = transport.requests[-1]
        assert dict(request.url.params) == {"app_version": "v2"}
        row = sub_row(env, TABLE)
        assert row["raw"] == STARTED and row["http_status"] == 200
        assert (row["candidate_count"], row["started_count"], row["started_promotion_keys"]) == (
            6,
            1,
            ["C-MLA1669550"],
        )
        assert queue_row(env, ITEM) is None

    def test_promotions_in_bundle_resources_without_the_flag_makes_no_call_and_is_counted(self, env) -> None:
        enable_refresh(bundle_resources=["core", "promotions"])
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert sql_scalar(env, f"SELECT count(*) FROM {TABLE}") == 0
        assert counters_of(env)["skipped_disabled"] == {"promotions": 1}
        assert queue_row(env, ITEM) is None

    def test_the_flag_without_promotions_in_bundle_resources_makes_no_call(self, env) -> None:
        enable_refresh(promotions__enabled=True)  # bundle_resources defaults to ["core"]
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_for())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert sql_scalar(env, f"SELECT count(*) FROM {TABLE}") == 0

    def test_an_explicit_promotions_entry_with_the_flag_off_is_dropped_without_a_call(self, env) -> None:
        enable_refresh(bundle_resources=["core", "promotions"])
        enqueue_items(ITEM, resources=("promotions",))

        make_handler(NoCallTransport()).run(context())

        assert queue_row(env, ITEM) is None  # dropped uncharged
        assert counters_of(env)["skipped_disabled"] == {"promotions": 1}

    def test_the_kill_switch_stops_the_promotions_fetch_even_with_both_flags(self, env, monkeypatch) -> None:
        enable_refresh(**ENABLED)
        enqueue_items(ITEM, resources=("promotions",))
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)

        make_handler(NoCallTransport()).run(context())

        assert sql_scalar(env, f"SELECT count(*) FROM {TABLE}") == 0


class TestMinimumAge:
    def test_the_bundle_does_not_refetch_promotions_checked_less_than_300_seconds_ago(self, env) -> None:
        enable_refresh(**ENABLED)
        enqueue_items(ITEM)
        make_handler(ScriptedTransport(responder_for())).run(context())
        with env.begin() as conn:
            conn.execute(text(f"UPDATE {TABLE} SET last_checked_at = now() - interval '299 seconds'"))

        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_for())
        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert counters_of(env)["skipped_min_age"] == {"promotions": 1}

    def test_the_bundle_refetches_promotions_older_than_300_seconds(self, env) -> None:
        enable_refresh(**ENABLED)
        enqueue_items(ITEM)
        make_handler(ScriptedTransport(responder_for())).run(context())
        with env.begin() as conn:
            conn.execute(text(f"UPDATE {TABLE} SET last_checked_at = now() - interval '301 seconds'"))

        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_for())
        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk", f"/seller-promotions/items/{ITEM}"]

    def test_an_explicit_promotions_entry_bypasses_the_minimum_age_and_skips_the_core(self, env) -> None:
        enable_refresh(**ENABLED)
        enqueue_items(ITEM)
        make_handler(ScriptedTransport(responder_for())).run(context())  # promotions just checked

        enqueue_items(ITEM, resources=("promotions",))
        transport = ScriptedTransport(responder_for())
        make_handler(transport).run(context())

        assert paths(transport) == [f"/seller-promotions/items/{ITEM}"]
        assert queue_row(env, ITEM) is None


class TestStoreAndEvents:
    def test_a_candidate_that_starts_logs_one_row_of_that_entry_and_one_activated_event(self, env) -> None:
        enable_refresh(**ENABLED, events__enabled=True)
        enqueue_items(ITEM, resources=("promotions",))
        make_handler(ScriptedTransport(responder_for(CANDIDATES))).run(context())
        assert sql_scalar(env, "SELECT count(*) FROM ml_change_log") == 0  # first sighting: no row, no event
        assert sql_scalar(env, "SELECT count(*) FROM ml_item_events") == 0

        enqueue_items(ITEM, resources=("promotions",))
        make_handler(ScriptedTransport(responder_for(started_campaign()))).run(context())

        (log,) = sql_all(env, "SELECT resource_type, kind, changed_paths FROM ml_change_log")
        assert (log["resource_type"], log["kind"]) == ("promotions", "change")
        assert sorted(log["changed_paths"]) == [f"[{CAMPAIGN}].price", f"[{CAMPAIGN}].status"]
        (event,) = sql_all(
            env, "SELECT event_type, promotion_id, promotion_type, old_value, new_value, item_id FROM ml_item_events"
        )
        assert (event["event_type"], event["promotion_id"], event["promotion_type"]) == (
            "promotion_activated",
            CAMPAIGN,
            "SELLER_CAMPAIGN",
        )
        assert (event["old_value"], event["new_value"], event["item_id"]) == ("candidate", "1900000", ITEM)
        row = sub_row(env, TABLE)
        assert (row["candidate_count"], row["started_count"], row["started_promotion_keys"]) == (7, 1, [CAMPAIGN])

    def test_a_started_promotion_that_leaves_the_list_is_one_finished_event_absent(self, env) -> None:
        enable_refresh(**ENABLED, events__enabled=True)
        enqueue_items(ITEM, resources=("promotions",))
        make_handler(ScriptedTransport(responder_for(started_campaign()))).run(context())
        gone = [e for e in started_campaign() if e.get("id") != CAMPAIGN]  # real list, the started campaign removed

        enqueue_items(ITEM, resources=("promotions",))
        make_handler(ScriptedTransport(responder_for(gone))).run(context())

        (event,) = sql_all(env, "SELECT event_type, promotion_id, old_value, payload FROM ml_item_events")
        assert (event["event_type"], event["promotion_id"], event["old_value"]) == (
            "promotion_finished",
            CAMPAIGN,
            "started",
        )
        assert event["payload"] == {"reason": "absent"}

    def test_events_off_stores_the_change_but_writes_no_event(self, env) -> None:
        enable_refresh(**ENABLED)  # events.enabled stays off
        enqueue_items(ITEM, resources=("promotions",))
        make_handler(ScriptedTransport(responder_for(CANDIDATES))).run(context())

        enqueue_items(ITEM, resources=("promotions",))
        make_handler(ScriptedTransport(responder_for(started_campaign()))).run(context())

        assert sql_scalar(env, "SELECT count(*) FROM ml_change_log") == 1
        assert sql_scalar(env, "SELECT count(*) FROM ml_item_events") == 0

    def test_a_404_is_a_state_never_existed_and_the_entry_completes(self, env) -> None:
        enable_refresh(**ENABLED)
        enqueue_items(ITEM, resources=("promotions",))
        transport = ScriptedTransport(responder_for(response=json_response(NOT_FOUND["body"], status=404)))

        make_handler(transport).run(context())

        row = sub_row(env, TABLE)
        assert (row["http_status"], row["never_existed"], row["raw"]) == (404, True, None)
        assert queue_row(env, ITEM) is None

    def test_a_500_is_stored_and_retried_for_promotions_alone(self, env) -> None:
        """Synthetic fault: promotions answers 500 (nothing 5xx was captured)."""
        enable_refresh(**ENABLED)
        enqueue_items(ITEM)
        body = {"message": "internal", "error": "internal_error", "status": 500, "cause": []}
        make_handler(ScriptedTransport(responder_for(response=json_response(body, status=500)))).run(context())

        row = sub_row(env, TABLE)
        assert (row["http_status"], row["error_body"], row["raw"]) == (500, body, None)
        queued = queue_row(env, ITEM)
        assert queued["resources"] == ["promotions"] and queued["attempts"] == 1
        assert "promotions: HTTP 500" in queued["last_error"]

        release_backoff(env)
        retry = ScriptedTransport(responder_for())
        make_handler(retry).run(context())

        assert paths(retry) == [f"/seller-promotions/items/{ITEM}"]  # no core call on the retry
        assert sub_row(env, TABLE)["raw"] == STARTED
        assert queue_row(env, ITEM) is None
