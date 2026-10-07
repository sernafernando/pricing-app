"""The refresh handler's user product, stock and family fetchers (design D12): the item bundle reaches them
through the stored item row; entries of kind `user_product` and `family` carry no item at all.

Postgres only. The core is the real `/items/bulk` capture (MLA935110613: user product MLAU282291766, family
7695306917964170; MLA934406852: MLAU312190127, 4395795880542864); the user product, stock and family bodies are
the real captures of 2026-10-06 served for whatever id is asked (rows are keyed by the REQUESTED id). A test
that needs an item without a user product says so: it is a real element with two fields changed. Transport
faults (403, 404 body) are labelled synthetic: none was captured.
"""

from __future__ import annotations

import copy
import re

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications.pacing import Pacer
from app.services.ml_publications.queue import LANE_MANUAL, EnqueueEntry, enqueue
from tests.services.ml_publications.conftest import subresource_body
from tests.workers.handlers.test_ml_publications_bundle_policy import paths
from tests.workers.handlers.test_ml_publications_refresh import (
    FakeClock,
    NoCallTransport,
    ScriptedTransport,
    bulk_answer,
    bulk_responder,
    context,
    counters_of,
    enable_refresh,
    enqueue_items,
    json_response,
    make_handler,
    sql_all,
    sql_one,
    sql_scalar,
)

pytestmark = pytest.mark.postgres

ITEM = "MLA935110613"
OTHER_ITEM = "MLA934406852"
UP, FAMILY = "MLAU282291766", 7695306917964170
OTHER_UP, OTHER_FAMILY = "MLAU312190127", 4395795880542864
ALL = ["core", "user_product", "stock", "family"]
USER_PRODUCT_PATH = re.compile(r"^/user-products/(?P<id>[^/]+)(?P<stock>/stock)?$")
FAMILY_PATH = re.compile(r"^/sites/MLA/user-products-families/(?P<id>\d+)$")
UP_BODY = subresource_body("user_product", "user_product_MLAU245334053")
STOCK_BODY = subresource_body("stock", "user_product_stock_MLAU245334053")  # 2 + 0
FAMILY_BODY = subresource_body("family", "family_5385385211222674")
FORBIDDEN = {"message": "forbidden", "error": "forbidden", "status": 403, "cause": []}  # synthetic
NOT_FOUND = {"message": "not found", "error": "not_found", "status": 404, "cause": []}  # synthetic


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


def responder_with(*, overrides: dict | None = None, bulk=bulk_responder):
    """Bulk for `/items/bulk`, the captured user product / stock / family bodies for their paths;
    `overrides` maps `user_product` / `stock` / `family` to a ready `httpx.Response`."""
    overrides = overrides or {}

    def responder(request, call):
        path = request.url.path
        if path == "/items/bulk":
            return bulk(request, call)
        if match := USER_PRODUCT_PATH.match(path):
            name, body = ("stock", STOCK_BODY) if match["stock"] else ("user_product", UP_BODY)
        elif FAMILY_PATH.match(path):
            name, body = "family", FAMILY_BODY
        else:
            raise AssertionError(f"unexpected path {path}")
        return overrides[name] if name in overrides else json_response(copy.deepcopy(body))

    return responder


def enqueue_entity(kind: str, entity_id: str, resources=("bundle",)) -> None:
    enqueue([EnqueueEntry(kind=kind, entity_id=entity_id, lane=LANE_MANUAL, resources=tuple(resources))])


def queue_entry(engine, kind: str, entity_id: str):
    return sql_one(engine, "SELECT * FROM ml_pub_refresh_queue WHERE kind = :k AND entity_id = :i", k=kind, i=entity_id)


def row(engine, table: str, column: str, key):
    return sql_one(engine, f"SELECT * FROM {table} WHERE {column} = :k", k=key)


def without_user_product(request, call):
    """Real element of `/items/bulk`, `user_product_id` and `family_id` changed to null."""
    answer = bulk_answer(request.url.params["ids"].split(","))
    for element in answer:
        element["body"]["user_product_id"] = None
        element["body"]["family_id"] = None
    return json_response(answer)


def shared_user_product(request, call):
    """Real elements of two items, both pointed at MLAU282291766 (`user_product_id` changed on the second)."""
    answer = bulk_answer(request.url.params["ids"].split(","))
    for element in answer:
        element["body"]["user_product_id"] = UP
    return json_response(answer)


def distinct_user_products(request, call):
    """Real element of MLA935110613 served for every requested id, each with its own `user_product_id`
    (`id` and `user_product_id` changed), so three items mean three user products."""
    template = bulk_answer([ITEM])[0]
    answer = []
    for number, item_id in enumerate(request.url.params["ids"].split(",")):
        element = copy.deepcopy(template)
        element["id"] = element["body"]["id"] = item_id
        element["body"]["user_product_id"] = f"MLAU{number + 1}"
        answer.append(element)
    return json_response(answer)


class TestItemBundle:
    def test_the_bundle_fetches_the_user_product_stock_and_family_of_the_item_after_the_core(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport)[0] == "/items/bulk"
        assert sorted(paths(transport)[1:]) == sorted(
            [f"/user-products/{UP}", f"/user-products/{UP}/stock", f"/sites/MLA/user-products-families/{FAMILY}"]
        )
        up = row(env, "ml_user_products", "user_product_id", UP)
        assert up["raw"] == UP_BODY and up["http_status"] == 200 and up["family_id"] == 5385385211222674
        assert row(env, "ml_user_product_stock", "user_product_id", UP)["total_quantity"] == 2
        family = row(env, "ml_user_product_families", "family_id", FAMILY)
        assert family["raw"] == FAMILY_BODY and family["user_products_ids"] == ["MLAU245334053"]
        assert queue_entry(env, "item", ITEM) is None

    def test_with_only_the_core_enabled_the_user_product_is_never_requested(self, env) -> None:
        enable_refresh()
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert sql_scalar(env, "SELECT count(*) FROM ml_user_products") == 0

    def test_enabling_only_stock_requests_only_the_stock_of_the_item_user_product(self, env) -> None:
        enable_refresh(bundle_resources=["core", "stock"])
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk", f"/user-products/{UP}/stock"]
        assert sql_scalar(env, "SELECT count(*) FROM ml_user_products") == 0

    def test_an_item_without_a_user_product_makes_no_call_for_it_and_completes(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with(bulk=without_user_product))

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert queue_entry(env, "item", ITEM) is None  # nothing to fetch is not a failure
        assert counters_of(env)["skipped_not_applicable"] == {"user_product": 1, "stock": 1, "family": 1}

    def test_two_items_of_one_user_product_in_a_batch_fetch_it_once(self, env) -> None:
        enable_refresh(bundle_resources=["core", "user_product", "stock"])
        enqueue_items(ITEM, OTHER_ITEM)
        transport = ScriptedTransport(responder_with(bulk=shared_user_product))

        make_handler(transport).run(context())

        assert sorted(paths(transport)) == sorted(["/items/bulk", f"/user-products/{UP}", f"/user-products/{UP}/stock"])
        assert queue_entry(env, "item", ITEM) is None and queue_entry(env, "item", OTHER_ITEM) is None
        assert counters_of(env)["skipped_shared"] == {"user_product": 1, "stock": 1}

    def test_a_shared_failure_is_charged_to_both_items(self, env) -> None:
        enable_refresh(bundle_resources=["core", "stock"])
        enqueue_items(ITEM, OTHER_ITEM)
        transport = ScriptedTransport(
            responder_with(overrides={"stock": json_response(FORBIDDEN, status=403)}, bulk=shared_user_product)
        )

        make_handler(transport).run(context())

        assert sum(1 for p in paths(transport) if p.endswith("/stock")) == 1
        for item in (ITEM, OTHER_ITEM):
            entry = queue_entry(env, "item", item)
            assert list(entry["resources"]) == ["stock"] and entry["attempts"] == 1


class TestMinimumAge:
    def checked(self, env, table: str, seconds: int) -> None:
        with env.begin() as conn:
            conn.execute(text(f"UPDATE {table} SET last_checked_at = now() - make_interval(secs => {seconds})"))

    def test_user_product_and_stock_wait_15_minutes_and_the_family_24_hours(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_items(ITEM)
        make_handler(ScriptedTransport(responder_with())).run(context())
        self.checked(env, "ml_user_products", 14 * 60)
        self.checked(env, "ml_user_product_stock", 14 * 60)
        self.checked(env, "ml_user_product_families", 23 * 3600)

        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with())
        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert counters_of(env)["skipped_min_age"] == {"user_product": 1, "stock": 1, "family": 1}

    def test_older_than_the_minimum_age_they_are_fetched_again(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_items(ITEM)
        make_handler(ScriptedTransport(responder_with())).run(context())
        self.checked(env, "ml_user_products", 16 * 60)
        self.checked(env, "ml_user_product_stock", 16 * 60)
        self.checked(env, "ml_user_product_families", 25 * 3600)

        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with())
        make_handler(transport).run(context())

        assert len(paths(transport)) == 4  # core + the three

    def test_a_named_stock_entry_of_the_item_bypasses_the_age_and_skips_the_core(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_items(ITEM)
        make_handler(ScriptedTransport(responder_with())).run(context())  # everything just checked

        enqueue_items(ITEM, resources=("stock",))
        transport = ScriptedTransport(responder_with())
        make_handler(transport).run(context())

        assert paths(transport) == [f"/user-products/{UP}/stock"]
        assert queue_entry(env, "item", ITEM) is None

    def test_a_named_stock_entry_of_an_item_never_fetched_is_not_applicable(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_items(ITEM, resources=("stock",))  # no stored row: the user product is unknown

        make_handler(NoCallTransport()).run(context())

        assert queue_entry(env, "item", ITEM) is None
        assert counters_of(env)["skipped_not_applicable"] == {"stock": 1}


class TestFailures:
    def test_a_stock_403_is_recorded_surfaced_and_charged_to_stock_alone(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with(overrides={"stock": json_response(FORBIDDEN, status=403)}))

        make_handler(transport).run(context())

        stock = row(env, "ml_user_product_stock", "user_product_id", UP)
        assert stock["http_status"] == 403 and stock["error_body"] == FORBIDDEN and stock["last_error"] == "HTTP 403"
        assert row(env, "ml_user_products", "user_product_id", UP)["http_status"] == 200  # the others applied
        entry = queue_entry(env, "item", ITEM)
        assert list(entry["resources"]) == ["stock"] and entry["attempts"] == 1
        assert entry["last_error"] == "stock: HTTP 403"
        assert counters_of(env)["subresources"]["stock"] == {"error_recorded": 1}
        assert counters_of(env)["endpoints"]["stock"]["4xx"] == 1

    def test_a_user_product_404_is_a_state_not_a_failure(self, env) -> None:
        enable_refresh(bundle_resources=["core", "user_product"])
        enqueue_items(ITEM)
        transport = ScriptedTransport(responder_with(overrides={"user_product": json_response(NOT_FOUND, status=404)}))

        make_handler(transport).run(context())

        stored = row(env, "ml_user_products", "user_product_id", UP)
        assert stored["never_existed"] is True and stored["http_status"] == 404
        assert queue_entry(env, "item", ITEM) is None


class TestStockPacing:
    def test_stock_calls_wait_for_their_own_sub_budget_although_the_global_budget_allows_more(self, env) -> None:
        enable_refresh(bundle_resources=["core", "stock"], rate_per_sec=20, stock_rate_per_min=30)  # 1 per 2 s
        enqueue_items(ITEM, OTHER_ITEM, "MLA874027718")
        clock = FakeClock()
        transport = ScriptedTransport(responder_with(bulk=distinct_user_products))

        make_handler(transport, pacer=Pacer(clock=clock)).run(context())

        stock_calls = [p for p in paths(transport) if p.endswith("/stock")]
        assert len(stock_calls) == 3
        assert clock.t - 1000.0 >= 4.0  # two waits of 2 s; the 20/s global budget alone would need 0.2 s

    def test_calls_that_are_not_stock_only_pay_the_global_budget(self, env) -> None:
        enable_refresh(bundle_resources=["core", "user_product"], rate_per_sec=20, stock_rate_per_min=30)
        enqueue_items(ITEM, OTHER_ITEM, "MLA874027718")
        clock = FakeClock()
        transport = ScriptedTransport(responder_with(bulk=distinct_user_products))

        make_handler(transport, pacer=Pacer(clock=clock)).run(context())

        assert len([p for p in paths(transport) if p.startswith("/user-products/")]) == 3
        assert clock.t - 1000.0 < 1.0


class TestUserProductEntries:
    def test_a_stock_entry_of_a_user_product_is_fetched_without_any_item(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_entity("user_product", UP, resources=("stock",))
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport) == [f"/user-products/{UP}/stock"]
        assert row(env, "ml_user_product_stock", "user_product_id", UP)["total_quantity"] == 2
        assert queue_entry(env, "user_product", UP) is None
        assert sql_scalar(env, "SELECT count(*) FROM ml_items") == 0

    def test_the_bundle_of_a_user_product_is_the_user_product_and_its_stock_only(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_entity("user_product", UP)
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert sorted(paths(transport)) == [f"/user-products/{UP}", f"/user-products/{UP}/stock"]
        assert queue_entry(env, "user_product", UP) is None

    def test_a_resource_of_another_entity_named_on_a_user_product_is_dropped_uncharged(self, env) -> None:
        enable_refresh(bundle_resources=ALL + ["prices"])
        enqueue_entity("user_product", UP, resources=("core", "prices"))

        make_handler(NoCallTransport()).run(context())

        entry = queue_entry(env, "user_product", UP)
        assert entry is None  # settled with nothing charged

    def test_a_disabled_stock_on_a_user_product_entry_is_dropped_uncharged_and_counted(self, env) -> None:
        enable_refresh(bundle_resources=["core", "user_product"])
        enqueue_entity("user_product", UP, resources=("stock",))

        make_handler(NoCallTransport()).run(context())

        assert queue_entry(env, "user_product", UP) is None
        assert counters_of(env)["skipped_disabled"] == {"stock": 1}

    def test_a_stock_403_keeps_the_user_product_entry_with_the_error(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_entity("user_product", UP, resources=("stock",))
        transport = ScriptedTransport(responder_with(overrides={"stock": json_response(FORBIDDEN, status=403)}))

        make_handler(transport).run(context())

        entry = queue_entry(env, "user_product", UP)
        assert entry["attempts"] == 1 and entry["last_error"] == "stock: HTTP 403"
        assert row(env, "ml_user_product_stock", "user_product_id", UP)["http_status"] == 403

    def test_items_and_user_products_are_claimed_in_the_same_run(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_items(ITEM)
        enqueue_entity("user_product", OTHER_UP, resources=("stock",))
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert f"/user-products/{OTHER_UP}/stock" in paths(transport) and "/items/bulk" in paths(transport)
        assert queue_entry(env, "item", ITEM) is None and queue_entry(env, "user_product", OTHER_UP) is None


class TestFamilyEntries:
    def test_a_family_entry_is_fetched_by_its_id_without_any_item(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_entity("family", str(OTHER_FAMILY), resources=("family",))
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport) == [f"/sites/MLA/user-products-families/{OTHER_FAMILY}"]
        stored = row(env, "ml_user_product_families", "family_id", OTHER_FAMILY)
        assert stored["raw"] == FAMILY_BODY and stored["http_status"] == 200
        assert queue_entry(env, "family", str(OTHER_FAMILY)) is None

    def test_a_family_entry_with_the_family_disabled_is_dropped_uncharged(self, env) -> None:
        enable_refresh(bundle_resources=["core", "stock"])
        enqueue_entity("family", str(FAMILY), resources=("family",))

        make_handler(NoCallTransport()).run(context())

        assert queue_entry(env, "family", str(FAMILY)) is None
        assert counters_of(env)["skipped_disabled"] == {"family": 1}

    def test_the_family_counters_use_the_family_endpoint(self, env) -> None:
        enable_refresh(bundle_resources=ALL)
        enqueue_entity("family", str(FAMILY), resources=("family",))

        make_handler(ScriptedTransport(responder_with())).run(context())

        assert counters_of(env)["endpoints"]["family"]["2xx"] == 1
        assert counters_of(env)["subresources"]["family"] == {"first_seen": 1}


class TestUnchangedAndLogged:
    def test_a_changed_stock_logs_one_row_for_the_user_product(self, env) -> None:
        """Real stock with the selling_address quantity 2 -> 5 on the second fetch."""
        enable_refresh(bundle_resources=ALL)
        enqueue_entity("user_product", UP, resources=("stock",))
        make_handler(ScriptedTransport(responder_with())).run(context())
        moved = copy.deepcopy(STOCK_BODY)
        next(loc for loc in moved["locations"] if loc["type"] == "selling_address")["quantity"] = 5

        enqueue_entity("user_product", UP, resources=("stock",))

        def responder(request, call):
            return json_response(copy.deepcopy(moved))

        make_handler(ScriptedTransport(responder)).run(context())

        logged = sql_all(env, "SELECT resource_type, entity_id, item_id, changed_paths FROM ml_change_log")
        assert [(r["resource_type"], r["entity_id"], r["item_id"]) for r in logged] == [("stock", UP, None)]
        assert logged[0]["changed_paths"] == ["locations[selling_address].quantity"]
