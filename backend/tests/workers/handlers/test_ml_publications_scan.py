"""`ml_publications.scan` (design D17): the daily lap with a 30 s catch-up, the disabled outcome, the
full-scan request path and the lap run records.

Postgres only. Every ML body is a captured scan response; a test that must prove "no ML call" uses a
transport that fails the test on any request.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import scans, settings_store
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.workers import registry
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers import ml_publications as handlers
from app.workers.runtime import WorkerRuntime
from tests.services.ml_publications.conftest import scan_body

pytestmark = pytest.mark.postgres

HANDLER_NAME = "ml_publications.scan"
ACTIVE = scan_body("active_page1")["results"]


class NoCallTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        pytest.fail(f"unexpected ML call: {request.url}")


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ScanTransport(httpx.BaseTransport):
    """Answers the first page of a status with its captured page and everything else with the captured
    empty answer (the end of a scroll). `after_call` runs after each request (to flip a flag mid-run)."""

    PAGES = {"active": "active_page1", "closed": "closed_page1", "paused": "paused_page1"}

    def __init__(self, after_call=None) -> None:
        self.requests: list[httpx.Request] = []
        self.after_call = after_call

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = request.url.params["status"]
        if "scroll_id" not in request.url.params and status in self.PAGES:
            body = scan_body(self.PAGES[status])
        else:
            body = scan_body("under_review_empty")
        if self.after_call:
            self.after_call(len(self.requests))
        return httpx.Response(200, json=body)

    def statuses(self) -> list[str]:
        return [r.url.params["status"] for r in self.requests]


def make_handler(transport: httpx.BaseTransport) -> handlers.ScanHandler:
    def factory(pacer: Pacer) -> MlHttpClient:
        return MlHttpClient(
            pacer=pacer, transport=transport, token_loader=lambda: {"access_token": "t", "expires_epoch": 9e12}
        )

    return handlers.ScanHandler(client_factory=factory, pacer=Pacer(clock=FakeClock()))


def context(seconds: float = 30.0) -> WorkerContext:
    return WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=seconds), worker_name="worker-ml")


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
    with mlpub_pg.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE worker_job_state (name varchar(64) PRIMARY KEY, last_run_at timestamptz, "
                "last_success_at timestamptz, state varchar(32), detail jsonb, heartbeat_at timestamptz)"
            )
        )
    monkeypatch.setattr(settings, "ML_USER_ID", "413658225")
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "1")
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    return mlpub_pg


def sql_all(engine, statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).mappings().all()


def sql_one(engine, statement: str, **params):
    rows = sql_all(engine, statement, **params)
    return rows[0] if rows else None


def sql_scalar(engine, statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).scalar()


def enable_scan(*, statuses=("active",), **other) -> None:
    settings_store.set_setting("scan.enabled", True, "test")
    settings_store.set_setting("scan.statuses", list(statuses), "test")
    for key, value in other.items():
        settings_store.set_setting(key.replace("__", "."), value, "test")


def detail_of(engine) -> dict:
    return sql_scalar(engine, "SELECT detail FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)


def store_one_item(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_items (item_id, status, last_checked_at, http_status) VALUES (:i, 'active', now(), 200)"
            ),
            {"i": ACTIVE[0]},
        )


class TestWiring:
    def test_it_runs_daily_at_0330_with_a_30_second_catch_up_and_no_notify(self) -> None:
        handler = handlers.scan
        assert handler.name == HANDLER_NAME
        assert handler.run_at_local == time(3, 30)
        assert handler.catch_up_interval == timedelta(seconds=30)
        assert handler.interval is None and handler.channels == ()

    def test_it_is_registered_in_the_ml_worker_registry(self) -> None:
        assert handlers.scan in registry.ML_PUBLICATIONS_REGISTRY

    def test_it_shares_the_global_pacer_of_the_refresh_handler(self) -> None:
        assert handlers.scan.pacer is handlers.refresh.pacer

    def test_the_handler_module_adds_no_cron_timer_or_notify(self) -> None:
        for path in (Path(handlers.__file__), Path(scans.__file__)):
            source = path.read_text(encoding="utf-8")
            assert not re.findall(r"crontab|OnCalendar|\.timer\b|pg_notify|\bLISTEN\b|\bNOTIFY\b", source), path


class TestDisabledOutcome:
    def test_the_flag_off_makes_no_call_and_no_write_and_reports_disabled(self, env) -> None:
        transport = NoCallTransport()
        result = make_handler(transport).run(context())

        assert result == JobResult(success=False, detail={"disabled": True})
        assert transport.requests == []
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_scan_state") == 0
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_job_runs") == 0
        assert sql_scalar(env, "SELECT count(*) FROM worker_job_state") == 0

    def test_the_kill_switch_overrides_an_enabled_row(self, env, monkeypatch) -> None:
        enable_scan()
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)
        transport = NoCallTransport()
        assert make_handler(transport).run(context()).detail == {"disabled": True}

    def test_the_runtime_keeps_a_disabled_scan_due_so_enabling_it_runs_it_on_the_next_pass(self, env) -> None:
        handler = make_handler(NoCallTransport())
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        after_the_slot = datetime(2026, 10, 6, 17, 0, tzinfo=timezone.utc)  # 14:00 Argentina

        assert runtime._run_handler(handler, after_the_slot) is False

        row = sql_one(env, "SELECT * FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)
        assert row["last_run_at"] is not None and row["last_success_at"] is None
        assert runtime._due_handlers(after_the_slot + timedelta(seconds=10)) == [handler]

    def test_a_pending_request_stays_set_while_disabled(self, env) -> None:
        with env.begin() as conn:
            conn.execute(
                text("INSERT INTO worker_job_state (name, state) VALUES (:n, 'requested')"), {"n": HANDLER_NAME}
            )
        handler = make_handler(NoCallTransport())
        WorkerRuntime(registry=[handler], direct_url=None).drain_once()
        assert sql_scalar(env, "SELECT state FROM worker_job_state WHERE name = :n", n=HANDLER_NAME) == "requested"

    def test_a_missing_seller_fails_closed_before_any_call(self, env, monkeypatch) -> None:
        enable_scan()
        monkeypatch.setattr(settings, "ML_USER_ID", None)
        transport = NoCallTransport()
        result = make_handler(transport).run(context())
        assert result.success is True  # the slot is consumed: no retry storm while the setup is missing
        assert result.detail["blocked"] == "seller_not_configured" and result.detail["complete"] is True
        assert transport.requests == []


class ScriptedUnauthorized(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid access token", "status": 401})


class ScriptedServerError(httpx.BaseTransport):
    def __init__(self) -> None:
        self.calls = 0
        self.healthy = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.healthy:
            return httpx.Response(200, json=scan_body("under_review_empty"))
        return httpx.Response(503, json={"message": "unavailable", "status": 503})


class TestSustainedUpstreamErrors:
    def test_a_persistent_server_error_stops_spinning_after_a_streak_and_falls_back_to_the_slot(self, env) -> None:
        enable_scan()
        transport = ScriptedServerError()
        handler = make_handler(transport)
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        now = datetime.now(timezone.utc)

        for _ in range(handlers.UPSTREAM_ERROR_STREAK - 1):
            assert runtime._run_handler(handler, now) is False  # a failed run: retried on the next pass
        assert runtime._run_handler(handler, now) is True  # the streak is over: blocked, not retried

        assert detail_of(env)["blocked"] == "upstream_error" and detail_of(env)["complete"] is True
        assert runtime._due_handlers(now + timedelta(seconds=31)) == []

    def test_the_log_blames_ml_not_the_setup_when_the_streak_ends(self, env, caplog) -> None:
        enable_scan()
        handler = make_handler(ScriptedServerError())
        with caplog.at_level("ERROR", logger=handlers.logger.name):
            for _ in range(handlers.UPSTREAM_ERROR_STREAK):
                handler.run(context())
        assert "upstream_error" in caplog.text and "setup" not in caplog.text

    def test_a_disabled_or_blocked_run_clears_the_streak(self, env, monkeypatch) -> None:
        enable_scan()
        handler = make_handler(ScriptedServerError())
        for _ in range(handlers.UPSTREAM_ERROR_STREAK - 1):
            assert handler.run(context()).success is False
        settings_store.set_setting("scan.enabled", False, "test")
        assert handler.run(context()).detail == {"disabled": True}
        settings_store.set_setting("scan.enabled", True, "test")
        assert handler.run(context()).success is False  # the old failures no longer count

        for _ in range(handlers.UPSTREAM_ERROR_STREAK - 2):
            assert handler.run(context()).success is False
        monkeypatch.setattr(settings, "ML_USER_ID", None)
        assert handler.run(context()).detail["blocked"] == "seller_not_configured"
        monkeypatch.setattr(settings, "ML_USER_ID", "413658225")
        assert handler.run(context()).success is False

    def test_our_own_exceptions_are_blocked_as_internal_not_as_an_ml_outage(self, env, monkeypatch) -> None:
        enable_scan()

        def explode(*args, **kwargs):
            raise RuntimeError("our bug")

        monkeypatch.setattr(scans, "run_scan", explode)
        handler = make_handler(NoCallTransport())
        results = [handler.run(context()) for _ in range(handlers.UPSTREAM_ERROR_STREAK)]
        assert [r.success for r in results] == [False] * (handlers.UPSTREAM_ERROR_STREAK - 1) + [True]
        assert results[-1].detail["blocked"] == "internal_error"

    def test_a_good_run_resets_the_streak(self, env) -> None:
        enable_scan()
        transport = ScriptedServerError()
        handler = make_handler(transport)
        for _ in range(handlers.UPSTREAM_ERROR_STREAK - 1):
            assert handler.run(context()).success is False
        transport.healthy = True
        assert handler.run(context()).success is True  # finished lap, streak cleared
        transport.healthy = False
        settings_store.set_setting("scan.next_mode", "full", "test")  # a new lap will start
        assert handler.run(context()).success is False  # first error of a new streak, not blocked


class TestBlockedBySetup:
    """Missing credentials must not leave the lap `complete=False`: that would spin the 30 s catch-up."""

    def blocked_run(self, env, monkeypatch, *, break_seller: bool):
        enable_scan()
        if break_seller:
            monkeypatch.setattr(settings, "ML_USER_ID", None)
        else:
            monkeypatch.setattr(settings, "ML_CLIENT_ID", None)
        handler = make_handler(NoCallTransport())
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        now = datetime.now(timezone.utc)
        assert runtime._run_handler(handler, now) is True
        return handler, runtime, now

    @pytest.mark.parametrize("break_seller", [True, False])
    def test_two_consecutive_due_checks_do_not_trigger_the_catch_up(self, env, monkeypatch, break_seller) -> None:
        handler, runtime, now = self.blocked_run(env, monkeypatch, break_seller=break_seller)

        assert detail_of(env)["complete"] is True and detail_of(env)["blocked"]
        assert runtime._due_handlers(now + timedelta(seconds=31)) == []
        assert runtime._due_handlers(now + timedelta(seconds=62)) == []

    def test_a_rejected_token_is_blocked_too_not_retried_every_30_seconds(self, env) -> None:
        enable_scan()
        transport = ScriptedUnauthorized()
        handler = make_handler(transport)
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        now = datetime.now(timezone.utc)

        assert runtime._run_handler(handler, now) is True

        assert detail_of(env)["blocked"] == "unauthorized" and detail_of(env)["complete"] is True
        assert runtime._due_handlers(now + timedelta(seconds=31)) == []
        assert runtime._due_handlers(now + timedelta(seconds=62)) == []

    def test_a_lap_left_open_by_an_earlier_run_is_also_blocked_not_retried(self, env, monkeypatch) -> None:
        enable_scan()

        def flag_off(call: int) -> None:
            settings_store.set_setting("scan.enabled", False, "test")

        make_handler(ScanTransport(after_call=flag_off)).run(context())  # lap open, complete=False persisted
        assert detail_of(env)["complete"] is False
        settings_store.set_setting("scan.enabled", True, "test")
        monkeypatch.setattr(settings, "ML_CLIENT_ID", None)
        handler = make_handler(NoCallTransport())
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        now = datetime.now(timezone.utc)

        assert runtime._run_handler(handler, now) is True

        assert runtime._due_handlers(now + timedelta(seconds=31)) == []

    def test_once_the_credentials_exist_the_scan_runs_and_resumes_the_open_lap(self, env, monkeypatch) -> None:
        handler, runtime, now = self.blocked_run(env, monkeypatch, break_seller=True)
        monkeypatch.setattr(settings, "ML_USER_ID", "413658225")
        from app.workers.scheduling import ARGENTINA_TZ

        tomorrow = now.astimezone(ARGENTINA_TZ).date() + timedelta(days=1)
        next_slot = datetime.combine(tomorrow, time(12, 0), tzinfo=ARGENTINA_TZ)  # after tomorrow's 03:30

        assert runtime._due_handlers(next_slot) == [handler]  # back on the daily schedule
        transport = ScanTransport()
        handler._client = None
        handler._client_factory = make_handler(transport)._client_factory

        assert handler.run(context()).detail["complete"] is True
        assert transport.statuses()[0] == "active"

    def test_a_request_while_blocked_is_honored_once_the_setup_exists(self, env, monkeypatch) -> None:
        handler, runtime, now = self.blocked_run(env, monkeypatch, break_seller=True)
        with env.begin() as conn:
            conn.execute(text("UPDATE worker_job_state SET state = 'requested' WHERE name = :n"), {"n": HANDLER_NAME})
        assert runtime._requested_handlers() == [handler]


class TestRun:
    def test_a_finished_lap_reports_success_complete_and_hands_the_day_back_to_the_schedule(self, env) -> None:
        enable_scan()
        transport = ScanTransport()
        handler = make_handler(transport)
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        after_the_slot = datetime.now(timezone.utc)

        assert runtime._run_handler(handler, after_the_slot) is True

        detail = detail_of(env)
        assert detail["complete"] is True and detail["mode"] == "full"  # empty store -> backfill
        assert detail["enumerated"] == 5 and detail["statuses"]["active"]["completed"] is True
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_refresh_queue WHERE lane = 3") == 5
        # complete=True: the 30 s catch-up is not in play, only the daily slot is
        assert runtime._due_handlers(after_the_slot + timedelta(minutes=1)) == []

    def test_an_unfinished_lap_keeps_the_catch_up_running_every_30_seconds(self, env) -> None:
        enable_scan(statuses=("closed", "active"))

        def flag_off_after_first_page(call: int) -> None:
            if call == 1:
                settings_store.set_setting("scan.enabled", False, "test")

        handler = make_handler(ScanTransport(after_call=flag_off_after_first_page))
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        now = datetime.now(timezone.utc)

        assert runtime._run_handler(handler, now) is True  # the pause is not a failure

        assert detail_of(env)["complete"] is False and detail_of(env)["stopped"] == "disabled"
        assert runtime._due_handlers(now + timedelta(seconds=10)) == []
        assert runtime._due_handlers(now + timedelta(seconds=31)) == [handler]

    def test_the_run_honors_the_configured_status_order(self, env) -> None:
        enable_scan(statuses=("closed", "paused"))
        transport = ScanTransport()
        make_handler(transport).run(context())
        assert transport.statuses()[0] == "closed" and "paused" in transport.statuses()
        assert "active" not in transport.statuses()

    def test_the_status_progress_is_kept_for_the_next_run_and_resumed(self, env) -> None:
        enable_scan()
        settings_store.set_setting("scan.next_mode", "rescan", "test")

        def flag_off_after_first_page(call: int) -> None:
            if call == 1:
                settings_store.set_setting("scan.enabled", False, "test")

        make_handler(ScanTransport(after_call=flag_off_after_first_page)).run(context())
        assert sql_scalar(env, "SELECT scroll_id FROM ml_pub_scan_state WHERE status = 'active'")

        settings_store.set_setting("scan.enabled", True, "test")
        transport = ScanTransport()
        assert make_handler(transport).run(context()).detail["complete"] is True
        assert "scroll_id" in transport.requests[0].url.params  # resumed, not restarted

    def test_a_transport_error_is_reported_as_a_failed_run_that_keeps_the_lap_open(self, env) -> None:
        enable_scan()

        class Boom(httpx.BaseTransport):
            def handle_request(self, request):
                raise httpx.ConnectError("down")

        result = make_handler(Boom()).run(context())
        assert result.success is False and result.error == "network"
        assert detail_of(env)["complete"] is False
        assert sql_scalar(env, "SELECT completed_at FROM ml_pub_scan_state WHERE status = 'active'") is None


class TestRequestedFullScan:
    def test_a_full_request_runs_a_backfill_even_with_stored_items_and_is_consumed_when_the_lap_completes(
        self, env
    ) -> None:
        store_one_item(env)
        enable_scan(scan__next_mode="full")
        make_handler(ScanTransport()).run(context())

        assert detail_of(env)["mode"] == "full"
        assert settings_store.get_setting("scan.next_mode").value == "rescan"

    def test_the_request_is_kept_while_the_lap_is_unfinished(self, env) -> None:
        store_one_item(env)
        enable_scan(scan__next_mode="full")

        def flag_off(call: int) -> None:
            settings_store.set_setting("scan.enabled", False, "test")

        make_handler(ScanTransport(after_call=flag_off)).run(context())

        assert settings_store.get_setting("scan.next_mode").value == "full"

    def test_without_a_request_a_store_with_items_runs_a_rescan_and_skips_fresh_items(self, env) -> None:
        store_one_item(env)
        enable_scan()
        make_handler(ScanTransport()).run(context())

        assert detail_of(env)["mode"] == "rescan"
        queued = {r["entity_id"] for r in sql_all(env, "SELECT entity_id FROM ml_pub_refresh_queue")}
        assert ACTIVE[0] not in queued and queued == set(ACTIVE[1:])  # the fresh stored item is skipped


class TestRunRecords:
    def test_a_finished_lap_leaves_one_success_record(self, env) -> None:
        enable_scan()
        make_handler(ScanTransport()).run(context())
        rows = sql_all(env, "SELECT job, scope, outcome, finished_at, counts FROM ml_pub_job_runs")
        assert [(r["job"], r["scope"], r["outcome"]) for r in rows] == [("scan", "full", "success")]
        assert rows[0]["finished_at"] is not None and rows[0]["counts"]["enumerated"] == 5

    def test_an_unexpected_error_is_recorded_and_the_worker_keeps_running(self, env, monkeypatch) -> None:
        enable_scan()

        def explode(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(scans, "run_scan", explode)
        handler = make_handler(NoCallTransport())
        runtime = WorkerRuntime(registry=[handler], direct_url=None)

        assert runtime._run_handler(handler, datetime.now(timezone.utc)) is False  # no exception escapes

        row = sql_one(env, "SELECT outcome, last_error FROM ml_pub_job_runs")
        assert row["outcome"] == "error" and "RuntimeError: boom" in row["last_error"]
        assert detail_of(env)["complete"] is False

    def test_an_error_inside_an_open_lap_annotates_that_lap_record(self, env, monkeypatch) -> None:
        enable_scan()

        def flag_off(call: int) -> None:
            settings_store.set_setting("scan.enabled", False, "test")

        make_handler(ScanTransport(after_call=flag_off)).run(context())  # opens the lap record
        settings_store.set_setting("scan.enabled", True, "test")
        monkeypatch.setattr(scans, "_enqueue_unseen", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("late")))

        result = make_handler(ScanTransport()).run(context())

        assert result.success is False
        rows = sql_all(env, "SELECT outcome, last_error FROM ml_pub_job_runs")
        assert len(rows) == 1 and rows[0]["outcome"] is None and "late" in rows[0]["last_error"]
