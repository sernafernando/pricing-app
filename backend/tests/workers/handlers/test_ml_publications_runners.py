"""`ml_publications.refresh` batch runners and the pipelined sub-resource calls (ml-freshness S1a).

Owner (2026-11-12): "pero por qué estamos haciendo una consulta a la vez 60 por minuto? si dijimos de hacer mínimo
10 por segundo?". The handler keeps the shared pacer busy while the queue has work: `refresh.runners` batch runners
claim -> process -> settle concurrently over the SKIP LOCKED claim, and a batch submits every sub-resource call at
once in `bundle.FETCH_ORDER` instead of waiting for each resource phase to finish.

Postgres only (queue claims, row locks). Transports block on events with a timeout, so a regression fails the test
instead of hanging it.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications.pacing import Pacer
from tests.workers.handlers.test_ml_publications_bundle_policy import ITEM, paths, responder_with, sub_row
from tests.workers.handlers.test_ml_publications_refresh import (
    ScriptedTransport,
    bulk_answer,
    bulk_responder,
    context,
    enable_refresh,
    enqueue_items,
    json_response,
    make_handler,
    queue_row,
    sql_scalar,
)

pytestmark = pytest.mark.postgres

WAIT_SECONDS = 5.0
OTHER = "MLA934406852"


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


def live_clones(serve):
    """`serve` for the sub-resources; `/items/bulk` answers every requested id with the real capture of ITEM, its
    id changed (one field), so each clone is a live item whose sub-resources are fetched."""

    def responder(request, call):
        if request.url.path != "/items/bulk":
            return serve(request, call)
        ids = request.url.params["ids"].split(",")
        answer = bulk_answer([ITEM] * len(ids))
        for element, requested in zip(answer, ids):
            element["body"]["id"] = element["id"] = requested
        return json_response(answer)

    return responder


class TestBatchRunners:
    def test_n_runners_process_n_batches_at_once_and_never_the_same_entry_twice(self, env) -> None:
        enable_refresh(bulk_max_ids=2, refresh__runners=3)
        ids = [f"MLA{n}" for n in range(500, 510)]
        enqueue_items(*ids)
        lock, in_flight, all_three = threading.Lock(), [0], threading.Event()
        overlapped: list[bool] = []

        def three_at_once(request, call):
            with lock:
                in_flight[0] += 1
                if in_flight[0] >= 3:
                    all_three.set()
            overlapped.append(all_three.wait(WAIT_SECONDS))  # one runner alone waits out the timeout and fails
            with lock:
                in_flight[0] -= 1
            return bulk_responder(request, call)

        transport = ScriptedTransport(three_at_once)
        result = make_handler(transport).run(context(seconds=60))

        assert result.success is True
        assert overlapped[:3] == [True, True, True]
        requested = [i for batch in transport.ids() for i in batch]
        assert sorted(requested) == sorted(ids)  # every entry once: no batch claimed what another runner holds
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_refresh_queue") == 0
        assert result.detail["claimed"] == 10  # batches may be smaller than 2: a claim skips the rows another locks

    def test_a_429_in_one_runner_stops_the_others_at_their_next_batch(self, env) -> None:
        """Synthetic fault: the first bulk answers 429 while a second runner's bulk is in flight."""
        enable_refresh(bulk_max_ids=1, refresh__runners=2)
        enqueue_items(ITEM, OTHER, "MLA1")
        first_answered, second_in_flight = threading.Event(), threading.Event()

        def limited_first(request, call):
            if call == 1:
                second_in_flight.wait(WAIT_SECONDS)
                first_answered.set()
                return json_response({"message": "too many"}, status=429, headers={"Retry-After": "30"})
            second_in_flight.set()
            first_answered.wait(WAIT_SECONDS)
            time.sleep(0.5)  # the 429 is registered by its runner long before this batch settles
            return bulk_responder(request, call)

        transport = ScriptedTransport(limited_first)
        result = make_handler(transport).run(context(seconds=60))

        assert result.detail["stopped"] == "rate_limited"
        assert len(transport.requests) == 2  # nobody claimed the third entry after the 429
        rows = [queue_row(env, i) for i in (ITEM, OTHER, "MLA1")]
        waiting = [r for r in rows if r is not None]
        assert len(waiting) == 2 and all((r["attempts"], r["claimed_at"]) == (0, None) for r in waiting)
        assert any(r["not_before"] > datetime.now(timezone.utc) + timedelta(seconds=20) for r in waiting)

    def test_one_runner_claims_one_batch_at_a_time(self, env) -> None:
        enable_refresh(bulk_max_ids=1, refresh__runners=1)
        enqueue_items(ITEM, OTHER)
        lock, in_flight, peak = threading.Lock(), [0], [0]

        def count(request, call):
            with lock:
                in_flight[0] += 1
                peak[0] = max(peak[0], in_flight[0])
            time.sleep(0.1)
            with lock:
                in_flight[0] -= 1
            return bulk_responder(request, call)

        make_handler(ScriptedTransport(count)).run(context())

        assert peak[0] == 1


class TestNoResourceBarrier:
    def test_a_slow_call_does_not_hold_back_the_next_resource_of_another_entry(self, env) -> None:
        enable_refresh(bundle_resources=["core", "prices", "description"], refresh__runners=1)
        enqueue_items(ITEM, OTHER)
        other_description = threading.Event()
        waited: list[bool] = []
        serve = responder_with()

        def slow_item_prices(request, call):
            if request.url.path == f"/items/{OTHER}/description":
                other_description.set()
            if request.url.path == f"/items/{ITEM}/prices":
                waited.append(other_description.wait(WAIT_SECONDS))  # the barrier would hold it until timeout
            return serve(request, call)

        transport = ScriptedTransport(slow_item_prices)
        result = make_handler(transport).run(context(seconds=60))

        assert result.success is True
        assert waited == [True]
        for item in (ITEM, OTHER):
            assert sub_row(env, "ml_item_prices", item)["http_status"] == 200, item
            assert queue_row(env, item) is None, item
        assert sum(path.endswith("/description") for path in paths(transport)) == 2


class TestThroughput:
    def test_the_calls_keep_the_pacer_rate_while_the_queue_has_work(self, env) -> None:
        """A fake ML answering in 100 ms (prod latency) behind a real-clock pacer at the prod 10/s. While the queue has work
        (after the runners' first bulk calls, before the last batch drains alone) the handler spends within 10 % of
        the budget, and never more: the pacer is the only gate."""
        rate, batches, size = 10, 6, 5
        enable_refresh(bundle_resources=["core", "prices", "sale_price"], bulk_max_ids=size, rate_per_sec=rate)
        enqueue_items(*[f"MLA{n}" for n in range(600, 600 + batches * size)])
        stamps: list[float] = []
        serve = live_clones(responder_with())

        def fast_ml(request, call):
            stamps.append(time.monotonic())
            time.sleep(0.1)
            return serve(request, call)

        transport = ScriptedTransport(fast_ml)
        result = make_handler(transport, pacer=Pacer(rate_per_sec=rate)).run(context(seconds=120))

        assert result.success is True
        assert len(stamps) == batches * (1 + 2 * size)
        busy = stamps[settings.ML_PUB_REFRESH_RUNNERS : -2 * size]  # skip the ramp-up and the last batch's tail
        achieved = (len(busy) - 1) / (busy[-1] - busy[0])
        assert rate * 0.9 <= achieved <= rate * 1.1, achieved
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_refresh_queue") == 0
