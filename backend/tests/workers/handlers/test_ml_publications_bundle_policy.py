"""The refresh handler's item bundle policy (design D12): sub-resource fetchers behind the
`bundle_resources` gate, partial success, targeted retries and minimum ages.

Postgres only. The core is the real `/items/bulk` capture; the sub-resource bodies are the real
captures of MLA874027718 served for whatever item is asked (the store keys rows by the REQUESTED
id, never by the body). Transport faults (500, 403, 429) are labelled synthetic: none was captured.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import store, subresource_store
from tests.services.ml_publications.conftest import subresource_body, subresource_call
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
    queue_row,
    sql_all,
    sql_one,
    sql_scalar,
)

pytestmark = pytest.mark.postgres


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


ITEM = "MLA935110613"
SUB_PATH = re.compile(r"^/items/(?P<item>[^/]+)/(?P<resource>description|prices|sale_price)$")
BODIES = {
    "description": subresource_body("description", "description_MLA874027718"),
    "prices": subresource_body("prices", "prices_MLA874027718"),
    "sale_price": subresource_body("sale_price", "sale_price_MLA874027718"),
}
NOT_FOUND = {
    "description": subresource_call("description", "description_unknown"),
    "prices": subresource_call("prices", "prices_unknown"),
}


def responder_with(overrides: dict | None = None, bodies: dict | None = None):
    """Bulk for `/items/bulk`, the captured body for each sub-resource path; `overrides` maps a
    resource to a ready `httpx.Response`."""
    overrides = overrides or {}
    served = {**BODIES, **(bodies or {})}

    def responder(request, call):
        if request.url.path == "/items/bulk":
            return bulk_responder(request, call)
        match = SUB_PATH.match(request.url.path)
        assert match, f"unexpected path {request.url.path}"
        resource = match["resource"]
        if resource in overrides:
            return overrides[resource]
        return json_response(copy.deepcopy(served[resource]))

    return responder


def paths(transport: ScriptedTransport) -> list[str]:
    return [r.url.path for r in transport.requests]


def release_backoff(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE ml_pub_refresh_queue SET not_before = now() - interval '1 second'"))


def sub_row(engine, table: str, item: str = ITEM):
    return sql_one(engine, f"SELECT * FROM {table} WHERE item_id = :i", i=item)


class TestTheGate:
    def test_with_only_the_core_enabled_only_items_bulk_is_called(self, env) -> None:
        enable_refresh()  # bundle_resources defaults to ["core"]
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert queue_row(env, ITEM) is None

    def test_enabling_description_fetches_it_after_the_core_and_stores_it(self, env) -> None:
        enable_refresh(bundle_resources=["core", "description"])
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk", f"/items/{ITEM}/description"]
        row = sub_row(env, "ml_item_descriptions")
        assert row["raw"] == BODIES["description"] and row["http_status"] == 200
        assert queue_row(env, ITEM) is None

    def test_sale_price_is_requested_with_the_marketplace_context(self, env) -> None:
        enable_refresh(bundle_resources=["core", "sale_price"])
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        request = transport.requests[-1]
        assert request.url.path == f"/items/{ITEM}/sale_price"
        assert dict(request.url.params) == {"context": "channel_marketplace"}
        assert sub_row(env, "ml_item_sale_prices")["price_id"] == "465"

    def test_a_named_resource_that_is_not_enabled_makes_no_call_and_is_counted_disabled(self, env) -> None:
        enable_refresh()
        enqueue_items(ITEM, resources=("prices",))

        make_handler(NoCallTransport()).run(context())

        assert queue_row(env, ITEM) is None  # dropped uncharged
        counters = counters_of(env)
        assert counters["skipped_disabled"] == {"prices": 1} and counters["skipped_no_fetcher"] == {}

    def test_an_item_whose_core_answers_404_gets_no_sub_resource_calls(self, env) -> None:
        enable_refresh(bundle_resources=["core", "prices"])
        enqueue_items("MLA1")
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert queue_row(env, "MLA1") is None


class TestPartialSuccess:
    def test_a_failing_description_stores_its_error_applies_the_others_and_retries_only_it(self, env) -> None:
        """Synthetic fault: description answers 500 (nothing 5xx was captured)."""
        enable_refresh(bundle_resources=["core", "description", "prices"])
        enqueue_items(ITEM)
        error_body = {"message": "internal", "error": "internal_error", "status": 500, "cause": []}
        transport = ScriptedTransport(responder_with({"description": json_response(error_body, status=500)}))

        make_handler(transport).run(context())

        description = sub_row(env, "ml_item_descriptions")
        assert (description["http_status"], description["error_body"], description["raw"]) == (500, error_body, None)
        assert sub_row(env, "ml_item_prices")["raw"] == BODIES["prices"]  # applied despite the failure
        queued = queue_row(env, ITEM)
        assert queued["resources"] == ["description"] and queued["attempts"] == 1
        assert "description: HTTP 500" in queued["last_error"]

        release_backoff(env)
        retry = ScriptedTransport(responder_with())
        make_handler(retry).run(context())

        assert paths(retry) == [f"/items/{ITEM}/description"]  # no core, no prices
        assert queue_row(env, ITEM) is None
        assert sub_row(env, "ml_item_descriptions")["raw"] == BODIES["description"]

    def test_a_403_is_recorded_and_visible_on_the_row_and_the_queue(self, env) -> None:
        """Synthetic fault: prices answers 403."""
        enable_refresh(bundle_resources=["core", "prices"])
        enqueue_items(ITEM)
        body = {"message": "forbidden", "error": "forbidden", "status": 403, "cause": []}
        transport = ScriptedTransport(responder_with({"prices": json_response(body, status=403)}))

        make_handler(transport).run(context())

        row = sub_row(env, "ml_item_prices")
        assert (row["http_status"], row["error_body"], row["last_error"]) == (403, body, "HTTP 403")
        assert "prices: HTTP 403" in queue_row(env, ITEM)["last_error"]

    def test_a_sub_resource_404_is_a_state_not_a_failure(self, env) -> None:
        enable_refresh(bundle_resources=["core", "description"])
        enqueue_items(ITEM)
        call = NOT_FOUND["description"]
        transport = ScriptedTransport(responder_with({"description": json_response(call["body"], status=404)}))

        make_handler(transport).run(context())

        row = sub_row(env, "ml_item_descriptions")
        assert (row["http_status"], row["never_existed"]) == (404, True)
        assert queue_row(env, ITEM) is None

    def test_a_malformed_2xx_is_charged_to_that_resource_only(self, env) -> None:
        enable_refresh(bundle_resources=["core", "description", "prices"])
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with({"description": json_response({"unexpected": True})}))

        make_handler(transport).run(context())

        assert sub_row(env, "ml_item_descriptions")["last_error"].startswith("malformed")
        assert sub_row(env, "ml_item_prices")["raw"] == BODIES["prices"]
        assert queue_row(env, ITEM)["resources"] == ["description"]

    def test_a_store_exception_on_one_resource_is_charged_to_it_and_the_others_still_apply(
        self, env, monkeypatch
    ) -> None:
        enable_refresh(bundle_resources=["core", "description", "prices"])
        enqueue_items(ITEM)
        original = subresource_store.apply_subresource

        def flaky(spec, key, response, **kwargs):
            if spec.name == "description":
                raise RuntimeError("lock timeout")
            return original(spec, key, response, **kwargs)

        monkeypatch.setattr(subresource_store, "apply_subresource", flaky)

        make_handler(ScriptedTransport(responder_with())).run(context())

        assert sub_row(env, "ml_item_prices")["raw"] == BODIES["prices"]
        queued = queue_row(env, ITEM)
        assert queued["resources"] == ["description"] and "lock timeout" in queued["last_error"]


class TestMinimumAges:
    def enable_all(self) -> None:
        enable_refresh(bundle_resources=["core", "description", "prices"])

    def test_a_recent_description_is_not_refetched_by_the_bundle_but_prices_always_are(self, env) -> None:
        self.enable_all()
        enqueue_items(ITEM)
        make_handler(ScriptedTransport(responder_with())).run(context())

        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with())
        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk", f"/items/{ITEM}/prices"]  # description 6 h, prices 0
        assert counters_of(env)["skipped_min_age"] == {"description": 1}
        assert queue_row(env, ITEM) is None

    def test_a_description_older_than_its_minimum_age_is_fetched_again(self, env) -> None:
        self.enable_all()
        enqueue_items(ITEM)
        make_handler(ScriptedTransport(responder_with())).run(context())
        with env.begin() as conn:
            conn.execute(text("UPDATE ml_item_descriptions SET last_checked_at = now() - interval '6 hours 1 minute'"))

        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with())
        make_handler(transport).run(context())

        assert f"/items/{ITEM}/description" in paths(transport)

    def test_an_explicit_named_resource_bypasses_the_minimum_age(self, env) -> None:
        self.enable_all()
        enqueue_items(ITEM)
        make_handler(ScriptedTransport(responder_with())).run(context())

        enqueue_items(ITEM, resources=("description",))
        transport = ScriptedTransport(responder_with())
        make_handler(transport).run(context())

        assert paths(transport) == [f"/items/{ITEM}/description"]  # just checked, fetched anyway

    def test_the_configured_minimum_age_is_read_from_the_setting(self, env) -> None:
        enable_refresh(bundle_resources=["core", "prices"], min_age_seconds={"prices": 3600})
        enqueue_items(ITEM)
        make_handler(ScriptedTransport(responder_with())).run(context())

        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with())
        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]


class TestPriceTopicEntries:
    def test_a_price_entry_fetches_only_prices_and_sale_price_without_the_core(self, env) -> None:
        enable_refresh(bundle_resources=["core", "description", "prices", "sale_price"])
        enqueue_items(ITEM, resources=("prices", "sale_price"))
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert sorted(paths(transport)) == [f"/items/{ITEM}/prices", f"/items/{ITEM}/sale_price"]
        assert queue_row(env, ITEM) is None
        assert sql_scalar(env, "SELECT count(*) FROM ml_items") == 0  # the core was never fetched

    def test_a_price_event_is_written_when_a_fetched_price_changed(self, env) -> None:
        enable_refresh(bundle_resources=["core", "prices"], events__enabled=True)
        enqueue_items(ITEM, resources=("prices",))
        make_handler(ScriptedTransport(responder_with())).run(context())
        changed = copy.deepcopy(BODIES["prices"])
        changed["prices"][0]["amount"] = 60000.0  # marketplace standard 55882.0 -> 60000.0

        enqueue_items(ITEM, resources=("prices",))
        make_handler(ScriptedTransport(responder_with(bodies={"prices": changed}))).run(context())

        events = sql_all(env, "SELECT event_type, price_kind, old_value, new_value FROM ml_item_events")
        assert [(e["event_type"], e["price_kind"], e["old_value"], e["new_value"]) for e in events] == [
            ("price_changed", "standard", "55882.0", "60000.0")
        ]


class TestInterruptions:
    def test_a_429_on_a_sub_resource_releases_uncharged_and_keeps_only_what_is_left(self, env) -> None:
        enable_refresh(bundle_resources=["core", "prices", "sale_price"])
        enqueue_items(ITEM)
        limited = json_response({"message": "too many"}, status=429, headers={"Retry-After": "30"})
        transport = ScriptedTransport(responder_with({"prices": limited}))

        result = make_handler(transport).run(context())

        assert result.detail["stopped"] == "rate_limited"
        queued = queue_row(env, ITEM)
        assert (queued["attempts"], queued["claimed_at"]) == (0, None)
        assert queued["resources"] == ["prices", "sale_price"]  # the core is done, both prices remain
        assert queued["not_before"] > datetime.now(timezone.utc) + timedelta(seconds=20)
        assert sql_scalar(env, "SELECT count(*) FROM ml_items") == 1  # the core stays applied

    def test_a_deadline_after_the_core_releases_the_unfetched_sub_resources_uncharged(self, env, monkeypatch) -> None:
        enable_refresh(bundle_resources=["core", "prices"])
        enqueue_items(ITEM)
        ctx = context(seconds=30)
        original = store.apply_fetch

        def spend_the_deadline(*args, **kwargs):
            outcome = original(*args, **kwargs)
            object.__setattr__(ctx, "deadline", datetime.now(timezone.utc) - timedelta(seconds=1))
            return outcome

        monkeypatch.setattr(store, "apply_fetch", spend_the_deadline)
        transport = ScriptedTransport(responder_with())

        result = make_handler(transport).run(ctx)

        assert paths(transport) == ["/items/bulk"] and result.detail["stopped"] == "deadline"
        queued = queue_row(env, ITEM)
        assert (queued["attempts"], queued["claimed_at"], queued["resources"]) == (0, None, ["prices"])


class TestFailuresBeforeAnInterruption:
    def test_a_failure_then_a_429_charges_it_and_keeps_only_the_sub_resources_left_never_the_core(self, env) -> None:
        """Synthetic faults: description 500, then prices 429 (the core was already applied)."""
        enable_refresh(bundle_resources=["core", "description", "prices", "sale_price"])
        enqueue_items(ITEM)
        error_body = {"message": "internal", "error": "internal_error", "status": 500, "cause": []}
        limited = json_response({"message": "too many"}, status=429, headers={"Retry-After": "30"})
        transport = ScriptedTransport(
            responder_with({"description": json_response(error_body, status=500), "prices": limited})
        )

        result = make_handler(transport).run(context())

        assert result.detail["stopped"] == "rate_limited"
        queued = queue_row(env, ITEM)
        assert queued["resources"] == ["description", "prices", "sale_price"]  # no `bundle`, no `core`
        assert queued["attempts"] == 1 and "description: HTTP 500" in queued["last_error"]

        release_backoff(env)
        retry = ScriptedTransport(responder_with())
        make_handler(retry).run(context())

        assert "/items/bulk" not in paths(retry)  # the applied core is not fetched again
        assert queue_row(env, ITEM) is None


class TestCounters:
    def test_outcomes_per_sub_resource_are_flushed(self, env) -> None:
        enable_refresh(bundle_resources=["core", "description", "prices"])
        enqueue_items(ITEM)

        make_handler(ScriptedTransport(responder_with())).run(context())

        counters = counters_of(env)
        assert counters["subresources"] == {"description": {"first_seen": 1}, "prices": {"first_seen": 1}}
        assert set(counters["endpoints"]) == {"items_bulk", "description", "prices"}
