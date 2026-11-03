"""Regression tests from the #2007/#2008 verification probes (ml-ads-cupones-display T3a): mapper edge cases,
idempotency, retries, stop rules through the real client, the pacer gate, the handler under the runtime's
scheduling, concurrency and the migration round trip."""

from __future__ import annotations

import re

import copy
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import text

from app.core.config import settings
from app.models.ml_order_discounts import MlOrderDiscountLine, MlOrderDiscounts, MlOrderDiscountsState
from app.services.ml_order_discounts import ingestion, mapper, store
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import DEADLINE, Pacer
from app.workers.context import WorkerContext
from app.workers.handlers import ml_order_discounts as handler_module
from app.workers.handlers.ml_order_discounts import OrderDiscountsHandler
from app.workers.scheduling import is_due
from tests.services.ml_order_discounts.conftest import fixture, restore_pg_types
from tests.services.ml_order_discounts.test_ingestion import FakeClient, NOW, payment, response, rows

GOOD = fixture("discounts_top_coupon_3")
NOT_FOUND = fixture("discounts_not_found")


class FakeClock:
    def __init__(self, at=NOW):
        self.t, self.base = 1000.0, at

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def now(self):
        return self.base + timedelta(seconds=self.t - 1000.0)

    def advance(self, s):
        self.t += s


def seed(sf, n, start=1):
    with sf() as db:
        for i in range(n):
            payment(db, 900000 + start + i, start + i, "10.00", minutes=start + i)


def real_client(clock, fn):
    return MlHttpClient(
        pacer=Pacer(clock=clock),
        transport=httpx.MockTransport(fn),
        token_loader=lambda: {"access_token": "t", "expires_epoch": 9e12},
        now=clock.now,
    )


def run_once(sf, client, clock, max_calls=30):
    return ingestion.run(sf, client, now=clock.now, deadline=clock.now() + timedelta(seconds=20), max_calls=max_calls)


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", "1", raising=False)
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "1", raising=False)
    monkeypatch.setattr(handler_module.settings, "ML_ADS_ENABLED", True)


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"cause": [], "error": "not_found", "message": "Campaign finished", "status": 404}, mapper.ERROR),
        ({"error": "internal_error", "message": "x", "status": 500}, mapper.ERROR),
        ({"error": "forbidden", "status": 403}, mapper.ERROR),
        ({"status": "404", "error": "discount_not_found"}, mapper.ERROR),
        ({"message": "x", "error": "boom"}, mapper.ERROR),
        ({"status": 404, "error": "discount_not_found", "details": [{}]}, mapper.NONE),
        ({"status": 500, "details": copy.deepcopy(GOOD["details"])}, mapper.ERROR),
        (None, mapper.ERROR),
        ("oops", mapper.ERROR),
        ([1], mapper.ERROR),
        ({"details": None}, mapper.ERROR),
        ({"details": {}}, mapper.ERROR),
    ],
)
def test_ml_error_inside_a_200(body, expected):
    assert mapper.classify(200, body) == expected


@pytest.mark.parametrize("bad", ["20000.0", "", None, True, False, float("nan"), float("inf"), 1e400, 10**400, [], {}])
def test_bad_amount_is_null_never_a_number(bad):
    body = copy.deepcopy(GOOD)
    body["details"][0]["items"][0]["amounts"]["seller"] = bad
    del body["details"][0]["items"][0]["amounts"]["total"]
    line = mapper.map_lines(1, body)[0]
    assert line.amount_seller is None and line.amount_total is None


# ---- idempotency / atomicity ------------------------------------------------------------------
@pytest.mark.postgres
def test_rewrite_does_not_duplicate_and_replaces_lines(session_factory):
    with session_factory() as db:
        store.write_fetch(db, 5, "ok", 200, GOOD, NOW)
    with session_factory() as db:
        store.write_fetch(db, 5, "ok", 200, GOOD, NOW)
    assert len(rows(session_factory, MlOrderDiscounts)) == 1
    assert len(rows(session_factory, MlOrderDiscountLine)) == 4
    with session_factory() as db:
        store.write_fetch(db, 5, "error", 500, None, NOW)
    assert rows(session_factory, MlOrderDiscountLine) == []


@pytest.mark.postgres
def test_failed_line_insert_leaves_no_half_order(session_factory):
    body = copy.deepcopy(GOOD)
    body["details"][-1]["items"][0]["amounts"]["total"] = 1e13  # maps fine, overflows Numeric(14,2) on the 4th line
    with pytest.raises(sa.exc.SQLAlchemyError):
        with session_factory() as db:
            store.write_fetch(db, 5, "ok", 200, body, NOW)
    assert rows(session_factory, MlOrderDiscounts) == [] and rows(session_factory, MlOrderDiscountLine) == []
    seed(session_factory, 1, start=5)
    res = ingestion.run(
        session_factory,
        FakeClient({5: response(200, body)}),
        now=lambda: NOW,
        deadline=NOW + timedelta(seconds=20),
        max_calls=5,
    )
    assert res.counts[mapper.ERROR] == 1 and rows(session_factory, MlOrderDiscountLine) == []
    with session_factory() as db:
        got = db.execute(text("SELECT status, attempts, body IS NULL, body::text FROM ml_order_discounts")).one()
    print("refused-body row:", got)
    assert got[0] == "error" and got[1] == 1


@pytest.mark.postgres
def test_bad_amount_goes_to_db_as_null(session_factory):
    body = copy.deepcopy(GOOD)
    body["details"][0]["items"][0]["amounts"]["seller"] = "20000.0"
    with session_factory() as db:
        store.write_fetch(db, 5, "ok", 200, body, NOW)
    got = sorted(rows(session_factory, MlOrderDiscountLine), key=lambda r: r.detail_index)
    assert got[0].amount_seller is None and got[0].amount_total == Decimal("20000.00")


# ---- selection / backfill ---------------------------------------------------------------------
@pytest.mark.postgres
def test_selection_only_coupon_sales_each_once_and_never_recalled(session_factory):
    with session_factory() as db:
        payment(db, 1, 10, "5.00")
        payment(db, 2, 10, "7.00", minutes=2)  # same order, two payments
        payment(db, 3, 11, "0")
        payment(db, 4, 12, None)
        payment(db, 5, 13, "-1.00")
        payment(db, 6, 14, "5.00", status="rejected")
        payment(db, 7, 15, "5.00", status="cancelled")
        payment(db, 8, 16, "5.00", status="pending")
        payment(db, 9, 17, "5.00", status="refunded")
        payment(db, 10, 18, "5.00", status="in_mediation")
    client = FakeClient({10: response(200, GOOD), 17: response(404, NOT_FOUND), 18: response(200, {"details": []})})
    res = ingestion.run(session_factory, client, now=lambda: NOW, deadline=NOW + timedelta(seconds=20), max_calls=30)
    assert sorted(client.paths) == [f"/orders/{o}/discounts" for o in (10, 17, 18)]
    assert res.pending_left == 0
    # a later refund/extra payment on a done order
    with session_factory() as db:
        payment(db, 11, 10, "1.00", status="refunded")
    for hours in (1, 2, 24):
        at = NOW + timedelta(hours=hours)
        ingestion.run(session_factory, client, now=lambda: at, deadline=at + timedelta(seconds=20), max_calls=30)
    assert len(client.paths) == 3


@pytest.mark.postgres
def test_full_backfill_calls_each_order_exactly_once(session_factory):
    seed(session_factory, 95)
    client = FakeClient({i: response(200, GOOD) for i in range(1, 96)})
    while True:
        r = ingestion.run(session_factory, client, now=lambda: NOW, deadline=NOW + timedelta(seconds=20), max_calls=30)
        if not r.calls:
            break
    assert len(client.paths) == 95 == len(set(client.paths))


# ---- retries -----------------------------------------------------------------------------------
@pytest.mark.postgres
def test_error_retries_hourly_five_times_and_poison_does_not_block(session_factory):
    seed(session_factory, 3)
    answers = {1: response(200, GOOD), 2: response(200, GOOD), 3: response(400, {"status": 400})}  # 3 is the newest
    client = FakeClient(answers)
    calls_at = []
    for minutes in range(0, 60 * 8, 10):
        at = NOW + timedelta(minutes=minutes)
        before = len(client.paths)
        ingestion.run(session_factory, client, now=lambda: at, deadline=at + timedelta(seconds=20), max_calls=1)
        if any(p == "/orders/3/discounts" for p in client.paths[before:]):
            calls_at.append(minutes)
    print("poison calls at minutes", calls_at)
    assert len(calls_at) == 5 and all(b - a >= 60 for a, b in zip(calls_at, calls_at[1:]))
    assert client.paths.count("/orders/1/discounts") == 1 and client.paths.count("/orders/2/discounts") == 1


@pytest.mark.postgres
def test_a_head_order_that_always_times_out_does_not_block_the_queue(session_factory):
    """One order that always times out: nothing counts against it, so does the queue ever move?"""
    seed(session_factory, 3)
    client = FakeClient({1: response(200, GOOD), 2: response(200, GOOD), 3: response(0, None, error="timeout")})
    for hours in range(0, 12):
        at = NOW + timedelta(hours=hours)
        ingestion.run(session_factory, client, now=lambda: at, deadline=at + timedelta(seconds=20), max_calls=30)
    assert "/orders/1/discounts" in client.paths


# ---- stop rules through the real client ----------------------------------------------------------
@pytest.mark.postgres
@pytest.mark.parametrize(
    "name,fn,stopped,row_status,http_calls",
    [
        (
            "429",
            lambda r: httpx.Response(429, headers={"Retry-After": "120"}, json={"status": 429}),
            "rate_limited",
            None,
            1,
        ),
        ("connect", "connect", "transport", "error", 1),  # deferred: attempts stay 0
        ("timeout", "timeout", "transport", "error", 1),
        ("401", lambda r: httpx.Response(401, json={"status": 401}), "blocked", None, 2),
        ("401body", lambda r: httpx.Response(200, json={"status": 401, "error": "x"}), "blocked", None, 1),
        ("429body", lambda r: httpx.Response(200, json={"status": 429, "error": "x"}), "rate_limited", None, 1),
        ("badjson", lambda r: httpx.Response(200, content=b"<html>"), None, "error", 2),
        ("502", lambda r: httpx.Response(502, content=b"<html>"), "unavailable", "error", 1),  # deferred like transport
        ("403", lambda r: httpx.Response(403, json={"status": 403}), None, "error", 2),
    ],
)
def test_stop_rules(session_factory, name, fn, stopped, row_status, http_calls):
    seed(session_factory, 2)
    clock = FakeClock()
    calls = []

    def transport(request):
        calls.append(request.url.path)
        if fn == "connect":
            raise httpx.ConnectError("x", request=request)
        if fn == "timeout":
            raise httpx.ReadTimeout("x", request=request)
        return fn(request)

    res = run_once(session_factory, real_client(clock, transport), clock)
    assert res.stopped == stopped, res
    assert len(calls) == http_calls
    got = rows(session_factory, MlOrderDiscounts)
    if row_status is None:
        assert got == []
    else:
        assert {r.status for r in got} == {row_status}
        if stopped in ("transport", "unavailable"):
            assert [r.attempts for r in got] == [0]
    if name == "429":
        assert res.backoff_until == clock.now() + timedelta(seconds=120)


@pytest.mark.postgres
def test_deadline_stops_with_no_call_and_no_row(session_factory):
    seed(session_factory, 2)
    clock = FakeClock()
    calls = []
    client = real_client(clock, lambda r: calls.append(1) or httpx.Response(200, json=GOOD))
    res = ingestion.run(
        session_factory, client, now=clock.now, deadline=clock.now() - timedelta(seconds=1), max_calls=5
    )
    assert res.stopped == "deadline" and not calls and rows(session_factory, MlOrderDiscounts) == []


@pytest.mark.postgres
def test_429_streak_persisted_and_spacing(session_factory):
    seed(session_factory, 2)
    clock = FakeClock()
    calls = []
    # fresh client per run = restart between runs: only the persisted state remains
    waits = []
    for _ in range(9):
        c = real_client(clock, lambda r: calls.append(clock.t) or httpx.Response(429, json={"status": 429}))
        res = run_once(session_factory, c, clock)
        assert res.stopped == "rate_limited" and res.calls == 1
        waits.append((res.backoff_until - clock.now()).total_seconds())
        blocked = run_once(session_factory, c, clock)
        assert blocked.stopped == "backoff" and blocked.calls == 0
        clock.t += waits[-1]
    print(waits)
    assert waits == [60, 120, 240, 480, 960, 1920, 3600, 3600, 3600]
    assert len(calls) == 9
    state = rows(session_factory, MlOrderDiscountsState)
    assert len(state) == 1 and state[0].consecutive_429 == 9


# ---- handler ------------------------------------------------------------------------------------
def drive(handler, clock, seconds, on_run=None, step=5.0):
    """The runtime's scheduling: a pass every 5 s, due from last_success_at."""
    last_success = None
    out = []
    end = clock.t + seconds
    while clock.t < end:
        now = clock.now()
        if is_due(handler, now=now, last_success_at=last_success):
            r = handler.run(WorkerContext(deadline=clock.now() + timedelta(seconds=30)))
            out.append((round(clock.t - 1000, 1), r))
            if r.success:
                last_success = clock.now()
        clock.advance(step)
    return out


@pytest.mark.postgres
def test_cap_30_per_any_minute_own_family_real_pacer(session_factory):
    seed(session_factory, 400)
    clock = FakeClock()
    pacer = Pacer(clock=clock)
    at = []

    def transport(request):
        at.append(clock.t)
        return httpx.Response(200, json=GOOD)

    client = MlHttpClient(
        pacer=pacer,
        transport=httpx.MockTransport(transport),
        token_loader=lambda: {"access_token": "t", "expires_epoch": 9e12},
        now=clock.now,
    )
    h = OrderDiscountsHandler(
        client_factory=lambda p: client,
        pacer=pacer,
        session_factory=session_factory,
        now=clock.now,
    )
    runs = drive(h, clock, 600)
    worst = max(sum(1 for t in at if s <= t < s + 60) for s in at)
    gaps = sorted(b - a for a, b in zip(at, at[1:]))
    print(
        "calls", len(at), "worst60", worst, "min gap", gaps[0], "busy run", [r[1].detail.get("calls") for r in runs][:8]
    )
    print(client.counters.snapshot())
    assert worst <= 30
    assert gaps[0] >= 2.0 - 1e-9  # the pacer gate spaces the calls (0.5/s); no burst at the global 2/s
    assert "order_discounts" in client.counters.snapshot()
    assert "order_discounts" in pacer._families


def test_disabled_never_builds_a_client(monkeypatch):
    monkeypatch.setattr(handler_module.settings, "ML_ADS_ENABLED", False)
    built = []
    h = OrderDiscountsHandler(client_factory=lambda p: built.append(1), pacer=Pacer())
    r = h.run(WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30)))
    assert r.success is False and r.detail == {"disabled": True} and not built


def test_a_failing_run_stays_reported_while_it_keeps_failing(monkeypatch):
    clock = FakeClock()

    def boom(*a, **k):
        raise sa.exc.ProgrammingError("SELECT", {}, Exception('relation "ml_order_discounts" does not exist'))

    monkeypatch.setattr(handler_module.ingestion, "run", boom)
    h = OrderDiscountsHandler(
        client_factory=lambda p: object(),
        pacer=Pacer(clock=clock),
        now=clock.now,
        session_factory=lambda: None,
    )
    runs = drive(h, clock, 300)
    print([(t, r.success, r.detail.get("stopped"), bool(r.error)) for t, r in runs])
    assert not [r for _, r in runs if r.success]


# ---- concurrency ----------------------------------------------------------------------------------
@pytest.mark.postgres
def test_concurrent_runs_do_not_double_call(session_factory):
    seed(session_factory, 10)
    client = FakeClient({i: response(200, GOOD) for i in range(1, 11)})
    gate = threading.Barrier(2)

    def go():
        gate.wait()
        ingestion.run(session_factory, client, now=lambda: NOW, deadline=NOW + timedelta(seconds=20), max_calls=30)

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    print("calls", len(client.paths), "distinct", len(set(client.paths)))
    assert len(client.paths) == len(set(client.paths))


# ---- migration --------------------------------------------------------------------------------
NAMES = ("ml_order_discounts", "ml_order_discount_lines", "ml_order_discounts_state")


@pytest.mark.postgres
def test_migration_round_trip_and_no_drift(pg_engine):
    from alembic.autogenerate import compare_metadata
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    from app.core.database import Base
    from tests.services.ml_order_discounts.test_migration import _load_migration
    from tests.services.ml_ads.test_account_level_migration import _script_directory

    restore_pg_types()
    assert len(_script_directory().get_heads()) == 1
    print("heads", _script_directory().get_heads())
    migration = _load_migration()
    index_migration = _load_migration("20261228_ml_pay_ops_coupon_idx")
    source = Path(migration.__file__).read_text()
    assert "ForeignKey" not in source and "alter_" not in source
    assert "op.execute(" not in source  # the tables revision runs no raw SQL
    # The index revision's only raw SQL is the index, built and dropped CONCURRENTLY, and its lock_timeout.
    index_source = Path(index_migration.__file__).read_text()
    executed = re.findall(r'op\.execute\(\s*f?"([^"]*)', index_source)
    assert executed and all("INDEX CONCURRENTLY IF" in sql or "lock_timeout" in sql for sql in executed), executed
    md = sa.MetaData()
    for n in NAMES:
        Base.metadata.tables[n].to_metadata(md)
    drop = "DROP TABLE IF EXISTS " + ", ".join(NAMES) + " CASCADE"
    drop_index = "DROP INDEX IF EXISTS ix_ml_payments_ops_coupon_order_id"
    from app.models.ml_payments import MlPaymentOps

    # The migration indexes `ml_payments_ops`: create it here so the test never depends on another test's tables.
    MlPaymentOps.__table__.create(bind=pg_engine, checkfirst=True)
    with pg_engine.begin() as conn:
        conn.execute(sa.text(drop))
        conn.execute(sa.text(drop_index))
    with pg_engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_name": lambda name, kind, parent: kind != "table" or name in NAMES,
            },
        )
        try:
            before = set(sa.inspect(conn).get_table_names())
            conn.commit()
            for _ in range(2):
                # `autocommit_block` (the CONCURRENTLY index revision) needs the migration's own transaction.
                with Operations.context(ctx), ctx.begin_transaction():
                    migration.upgrade()
                with Operations.context(ctx), ctx.begin_transaction():
                    index_migration.upgrade()
                diff = compare_metadata(ctx, md)
                print("drift:", diff)
                assert diff == []
                conn.commit()
                with Operations.context(ctx), ctx.begin_transaction():
                    index_migration.downgrade()
                with Operations.context(ctx), ctx.begin_transaction():
                    migration.downgrade()
                assert set(sa.inspect(conn).get_table_names()) == before
                conn.commit()
        finally:
            conn.rollback()
            with pg_engine.begin() as cleanup:
                cleanup.execute(sa.text(drop))
                cleanup.execute(sa.text(drop_index))


def test_billing_schedule_unchanged():
    from datetime import time

    from app.workers import registry
    from app.workers.handlers.ml_billing import CATCH_UP, billing

    names = [h.name for h in registry.ML_PUBLICATIONS_REGISTRY]
    assert names.index("ml_billing.sweep") == 11
    assert names.index("ml_orders.discounts") == 12
    assert names[-2:] == ["publicacion_repair.envio", "publicacion_repair.sku"]

    assert billing.interval is None and billing.run_at_local == time(5, 17) and billing.catch_up_interval == CATCH_UP
    assert handler_module.discounts.own_thread is True  # its paced runs never take a turn in the shared pass


@pytest.mark.postgres
def test_a_refused_body_is_stored_as_sql_null(session_factory):
    seed(session_factory, 1)
    body = copy.deepcopy(GOOD)
    body["details"][0]["items"][0]["id"] = "MLA\u0000"  # Postgres JSONB refuses a NUL
    run_once(session_factory, FakeClient({1: response(200, body)}), FakeClock())
    with session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM ml_order_discounts WHERE body IS NULL")).scalar() == 1


# ---- own thread ---------------------------------------------------------------------------------
def test_runs_in_its_own_thread_never_in_the_shared_pass():
    assert handler_module.discounts.own_thread is True
    assert handler_module.discounts.deadline_seconds > handler_module.RUN_BUDGET.total_seconds()


@pytest.mark.postgres
def test_own_thread_pace_is_close_to_the_gate_and_never_above_it(session_factory):
    """The runtime's own-thread loop: run, then wait `interval`. Measured over 10 minutes."""
    seed(session_factory, 400)
    clock = FakeClock()
    pacer = Pacer(clock=clock)
    at = []

    def transport(request):
        at.append(clock.t)
        return httpx.Response(200, json=GOOD)

    client = MlHttpClient(
        pacer=pacer,
        transport=httpx.MockTransport(transport),
        token_loader=lambda: {"access_token": "t", "expires_epoch": 9e12},
        now=clock.now,
    )
    h = OrderDiscountsHandler(
        client_factory=lambda p: client, pacer=pacer, session_factory=session_factory, now=clock.now
    )
    end = clock.t + 600
    while clock.t < end:
        h.run(WorkerContext(deadline=clock.now() + timedelta(seconds=h.deadline_seconds)))
        clock.advance(h.interval.total_seconds())
    per_minute = len([t for t in at if t < end]) / 10
    print("measured calls per minute", per_minute)
    assert 25 <= per_minute <= 30
    assert max(sum(1 for t in at if s <= t < s + 60) for s in at) <= 30


@pytest.mark.postgres
def test_a_transport_outage_is_reported_as_an_error(session_factory):
    seed(session_factory, 1)
    h = OrderDiscountsHandler(
        client_factory=lambda p: FakeClient({1: response(0, None, error="ConnectError")}),
        pacer=Pacer(),
        session_factory=session_factory,
        now=lambda: NOW,
    )
    r = h.run(WorkerContext(deadline=NOW + timedelta(seconds=60)))
    assert r.detail["stopped"] == "transport" and r.error == "no HTTP answer from ML: ConnectError"


@pytest.mark.postgres
def test_a_stop_request_ends_the_run_without_more_calls(session_factory):
    """Through the real client and pacer: the stop asked after the first call ends the wait for the next slot."""
    seed(session_factory, 5)
    clock = FakeClock()
    calls = []

    def transport(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=GOOD)

    r = ingestion.run(
        session_factory,
        real_client(clock, transport),
        now=clock.now,
        deadline=clock.now() + timedelta(seconds=60),
        max_calls=5,
        should_stop=lambda: bool(calls),
    )
    assert len(calls) == 1 and r.calls == 1 and r.stopped == DEADLINE
    assert [row.status for row in rows(session_factory, MlOrderDiscounts)] == ["ok"]
