"""The refresh handler fetches replenishment (P4b): a named entry of a user product, paced by its own sub-gate.

Postgres only. The body is the real full_1 capture of 2026-10-08 (`replenishment_20261008.json`) served for
whatever user product is asked; the 206 header and the 403 are synthetic (none was captured).
"""

from __future__ import annotations

import copy
import re

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications.pacing import Pacer
from tests.services.ml_publications.conftest import load_fixture
from tests.workers.handlers.test_ml_publications_bundle_policy import paths
from tests.workers.handlers.test_ml_publications_refresh import (
    FakeClock,
    NoCallTransport,
    ScriptedTransport,
    bulk_responder,
    context,
    counters_of,
    enable_refresh,
    enqueue_items,
    json_response,
    make_handler,
    sql_one,
)
from tests.workers.handlers.test_ml_publications_user_products import (
    ITEM,
    UP as ITEM_UP,
    enqueue_entity,
    queue_entry,
    without_user_product,
)

pytestmark = pytest.mark.postgres

UP = "MLAU228712304"
PATH = re.compile(r"^/marketplace/fbm/user-products/(?P<id>[^/]+)/replenishment$")
BODY = next(c["body"] for c in load_fixture("replenishment_20261008.json")["calls"] if c["name"] == "full_1")
ENABLED = ["core", "replenishment"]


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


def answering(status: int = 200, headers=None, body=None):
    def responder(request, call):
        assert PATH.match(request.url.path), request.url.path
        return json_response(copy.deepcopy(BODY if body is None else body), status=status, headers=headers)

    return responder


def stored(engine):
    return sql_one(engine, "SELECT * FROM ml_user_product_replenishment WHERE user_product_id = :k", k=UP)


def test_a_named_entry_fetches_the_endpoint_with_the_store_token_alone_and_stores_it(env) -> None:
    enable_refresh(bundle_resources=ENABLED)
    enqueue_entity("user_product", UP, resources=("replenishment",))
    transport = ScriptedTransport(answering())

    make_handler(transport).run(context())

    (request,) = transport.requests
    assert request.url.path == f"/marketplace/fbm/user-products/{UP}/replenishment"
    assert dict(request.url.params) == {"country": "AR"}
    assert not {"x-caller-id", "x-caller-siteid"} & set(request.headers)
    assert request.headers["authorization"].startswith("Bearer ")
    row = stored(env)
    assert (row["units_30d"], row["partial"], row["http_status"]) == (311, False, 200)
    assert queue_entry(env, "user_product", UP) is None


def test_a_206_with_x_content_missing_is_stored_ok_and_partial(env) -> None:
    enable_refresh(bundle_resources=ENABLED)
    enqueue_entity("user_product", UP, resources=("replenishment",))
    transport = ScriptedTransport(answering(206, {"x-content-missing": "sales_history"}))

    make_handler(transport).run(context())

    row = stored(env)
    assert (row["partial"], row["content_missing"], row["last_error"]) == (True, "sales_history", None)
    assert queue_entry(env, "user_product", UP) is None
    assert counters_of(env)["subresources"]["replenishment"] == {"first_seen": 1}


def test_a_403_keeps_the_previous_data_records_the_error_and_leaves_the_entry_to_retry(env) -> None:
    enable_refresh(bundle_resources=ENABLED)
    enqueue_entity("user_product", UP, resources=("replenishment",))
    make_handler(ScriptedTransport(answering())).run(context())
    enqueue_entity("user_product", UP, resources=("replenishment",))
    forbidden = {"message": "forbidden", "error": "forbidden", "status": 403, "cause": []}  # synthetic

    make_handler(ScriptedTransport(answering(403, body=forbidden))).run(context())

    row = stored(env)
    assert row["units_30d"] == 311 and row["raw"] == BODY and row["http_status"] == 403 and row["last_error"]
    entry = queue_entry(env, "user_product", UP)
    assert list(entry["resources"]) == ["replenishment"] and entry["last_error"] == "replenishment: HTTP 403"


def test_it_is_dropped_uncharged_while_not_listed_in_bundle_resources(env) -> None:
    enable_refresh(bundle_resources=["core"])
    enqueue_entity("user_product", UP, resources=("replenishment",))

    make_handler(NoCallTransport()).run(context())

    assert queue_entry(env, "user_product", UP) is None
    assert counters_of(env)["skipped_disabled"] == {"replenishment": 1}


def test_the_default_bundle_never_fetches_it_even_when_enabled(env) -> None:
    enable_refresh(bundle_resources=ENABLED)
    enqueue_entity("user_product", UP, resources=("bundle",))

    make_handler(NoCallTransport()).run(context())

    assert queue_entry(env, "user_product", UP) is None


def test_its_calls_wait_for_the_sub_budget_although_the_global_budget_allows_more(env) -> None:
    enable_refresh(bundle_resources=ENABLED, rate_per_sec=20, replenishment_rate_per_min=30)  # 1 per 2 s
    for number in range(3):
        enqueue_entity("user_product", f"MLAU{number + 1}", resources=("replenishment",))
    clock = FakeClock()
    transport = ScriptedTransport(answering())

    make_handler(transport, pacer=Pacer(clock=clock)).run(context())

    assert len(paths(transport)) == 3
    assert clock.t - 1000.0 >= 4.0  # two waits of 2 s; the 20/s global budget alone would need 0.2 s


def with_core(replenishment):
    """`/items/bulk` (real capture) for the core, `replenishment` for the endpoint."""

    def responder(request, call):
        return bulk_responder(request, call) if request.url.path == "/items/bulk" else replenishment(request, call)

    return responder


class TestResincronizar:
    """A named `replenishment` on an item entry (the panel's Resincronizar) reaches the user product of the item."""

    def test_it_bypasses_the_minimum_age_of_a_day(self, env) -> None:
        enable_refresh(bundle_resources=ENABLED, min_age_seconds={"replenishment": 86400})
        with env.begin() as conn:  # checked a minute ago: far inside the minimum age
            conn.execute(
                text(
                    "INSERT INTO ml_user_product_replenishment (user_product_id, last_checked_at) "
                    "VALUES (:u, now() - interval '1 minute')"
                ),
                {"u": ITEM_UP},
            )
        enqueue_items(ITEM, resources=("bundle", "replenishment"))
        transport = ScriptedTransport(with_core(answering()))

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk", f"/marketplace/fbm/user-products/{ITEM_UP}/replenishment"]
        assert sql_one(env, "SELECT units_30d FROM ml_user_product_replenishment WHERE user_product_id = :k", k=ITEM_UP)

    def test_an_item_without_a_user_product_is_skipped_without_error(self, env) -> None:
        enable_refresh(bundle_resources=ENABLED)
        enqueue_items(ITEM, resources=("bundle", "replenishment"))

        def no_up_core(request, call):
            if request.url.path == "/items/bulk":
                return without_user_product(request, call)
            raise AssertionError("no replenishment call expected")

        make_handler(ScriptedTransport(no_up_core)).run(context())

        assert queue_entry(env, "item", ITEM) is None  # settled, not retried
        assert counters_of(env)["skipped_not_applicable"] == {"replenishment": 1}
