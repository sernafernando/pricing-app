"""`ml_orders.discounts` under the real own-thread runtime, real client, real pacer and real Postgres: nothing is held
during the ML call, a stop ends the run without losing an answer, a restart asks only the rest, and the shared pacer
keeps both budgets."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import GRANTED, ORDER_DISCOUNTS_FAMILY, Pacer
from app.workers.handlers import ml_order_discounts as handler_module
from app.workers.handlers.ml_order_discounts import OrderDiscountsHandler
from app.workers.runtime import WorkerRuntime
from tests.services.ml_order_discounts.conftest import fixture
from tests.services.ml_order_discounts.test_ingestion import payment

GOOD = fixture("discounts_top_coupon_3")


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", "1", raising=False)
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "1", raising=False)
    monkeypatch.setattr(handler_module.settings, "ML_ADS_ENABLED", True)


def seed(sf, n):
    with sf() as db:
        for i in range(1, n + 1):
            payment(db, 900000 + i, i, "10.00", minutes=i)


def make_handler(sf, fn, pacer=None):
    pacer = pacer or Pacer()
    return OrderDiscountsHandler(
        pacer=pacer,
        session_factory=sf,
        client_factory=lambda p: MlHttpClient(
            pacer=p,
            transport=httpx.MockTransport(fn),
            token_loader=lambda: {"access_token": "t", "expires_epoch": 9e12},
        ),
    )


def make_runtime(handler):
    runtime = WorkerRuntime(registry=[handler], direct_url="")
    runtime._requested_handlers = lambda: []
    runtime._record_job_run = lambda *a, **k: None
    return runtime


def asked(sf):
    with sf() as db:
        return set(db.execute(text("SELECT order_id FROM ml_order_discounts")).scalars())


@pytest.mark.postgres
def test_no_connection_transaction_or_lock_is_held_during_the_ml_call(session_factory, pg_discounts_engine):
    seed(session_factory, 3)
    observed = []
    monitor = pg_discounts_engine.connect().execution_options(isolation_level="AUTOCOMMIT")

    def fn(request):
        observed.append(
            {
                "checked_out": pg_discounts_engine.pool.checkedout() - 1,  # minus the monitor
                "other_in_tx": monitor.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
                    )
                ).scalar(),
                "advisory": monitor.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")).scalar(),
                "relation_locks": monitor.execute(
                    text(
                        "SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                        "WHERE c.relname LIKE 'ml_order_discount%' OR c.relname = 'ml_payments_ops'"
                    )
                ).scalar(),
            }
        )
        return httpx.Response(200, json=GOOD)

    runtime = make_runtime(make_handler(session_factory, fn))
    try:
        runtime.start_own_threads()
        deadline = time.monotonic() + 15
        while len(observed) < 3 and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        runtime.stop()
        runtime.join_own_threads(timeout=15)
        monitor.close()
    assert len(observed) == 3
    assert all(o == {"checked_out": 0, "other_in_tx": 0, "advisory": 0, "relation_locks": 0} for o in observed)


@pytest.mark.postgres
def test_a_stop_mid_run_ends_quickly_leaves_nothing_open_and_a_fresh_process_resumes(
    session_factory, pg_discounts_engine
):
    seed(session_factory, 6)
    calls = []

    def fn(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=GOOD)

    runtime = make_runtime(make_handler(session_factory, fn))
    runtime.start_own_threads()
    deadline = time.monotonic() + 15
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    stopped_at = time.monotonic()
    runtime.stop()
    runtime.join_own_threads(timeout=15)
    took = time.monotonic() - stopped_at
    done = asked(session_factory)
    assert not any(t.is_alive() for t in runtime._own_threads)
    assert took < 5  # the run stops between calls, not after its whole batch
    assert len(calls) == len(done) < 6
    assert pg_discounts_engine.pool.checkedout() == 0

    # worker restart: a new handler, a new pacer, no in-memory state.
    fresh_calls = []

    def fresh(request):
        fresh_calls.append(request.url.path)
        return httpx.Response(200, json=GOOD)

    restarted = make_runtime(make_handler(session_factory, fresh))
    restarted.start_own_threads()
    deadline = time.monotonic() + 25
    while len(asked(session_factory)) < 6 and time.monotonic() < deadline:
        time.sleep(0.1)
    restarted.stop()
    restarted.join_own_threads(timeout=15)
    assert asked(session_factory) == {1, 2, 3, 4, 5, 6}
    assert not set(calls) & set(fresh_calls)  # no order asked twice


@pytest.mark.postgres
def test_a_stop_during_a_hanging_call_ends_within_the_http_call_and_loses_nothing(session_factory):
    seed(session_factory, 3)
    entered = threading.Event()
    release = threading.Event()

    def fn(request):
        entered.set()
        release.wait(5)
        return httpx.Response(200, json=GOOD)

    runtime = make_runtime(make_handler(session_factory, fn))
    runtime.start_own_threads()
    assert entered.wait(5)
    runtime.stop()
    assert runtime._own_threads[0].is_alive()  # the call in flight is not interrupted...
    release.set()
    runtime.join_own_threads(timeout=5)
    assert not runtime._own_threads[0].is_alive()
    assert len(asked(session_factory)) == 1  # ...and its answer is stored


@pytest.mark.postgres
def test_the_own_thread_never_overlaps_itself(session_factory, monkeypatch):
    seed(session_factory, 1)
    current, peak, runs = [0], [0], [0]
    lock = threading.Lock()
    real = handler_module.ingestion.run

    def counting(*a, **k):
        with lock:
            current[0] += 1
            runs[0] += 1
            peak[0] = max(peak[0], current[0])
        try:
            time.sleep(0.05)
            return real(*a, **k)
        finally:
            with lock:
                current[0] -= 1

    monkeypatch.setattr(handler_module.ingestion, "run", counting)
    handler = make_handler(session_factory, lambda r: httpx.Response(200, json=GOOD))
    handler.interval = timedelta(milliseconds=1)
    handler._idle = lambda result: None  # no idle pause: as many runs as possible
    runtime = make_runtime(handler)
    runtime.start_own_threads()
    time.sleep(1.5)
    runtime.stop()
    runtime.join_own_threads(timeout=5)
    assert runs[0] > 5 and peak[0] == 1 and len(runtime._own_threads) == 1


def test_the_shared_pacer_keeps_both_budgets_with_two_threads():
    pacer = Pacer()
    stamps = {"core": [], ORDER_DISCOUNTS_FAMILY: []}
    until = datetime.now(timezone.utc) + timedelta(seconds=7)

    def loop(family):
        while True:
            if pacer.acquire(family, until) != GRANTED:
                return
            stamps[family].append(time.monotonic())

    threads = [threading.Thread(target=loop, args=(f,)) for f in ("core", "core", ORDER_DISCOUNTS_FAMILY)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    merged = sorted(stamps["core"] + stamps[ORDER_DISCOUNTS_FAMILY])
    gaps = [b - a for a, b in zip(merged, merged[1:])]
    own = [b - a for a, b in zip(stamps[ORDER_DISCOUNTS_FAMILY], stamps[ORDER_DISCOUNTS_FAMILY][1:])]
    assert min(gaps) >= 0.45  # 2/s global, with timer slop
    assert min(own) >= 1.95  # 30/min family
    assert len(stamps["core"]) >= 8  # the other family keeps most of the budget
