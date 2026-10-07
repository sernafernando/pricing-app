"""`ml_publications.missed_feeds` (design D17): the 2 h interval job, its flag, its retry backoff and its resume.

Postgres only. Every ML body is a captured `/missed_feeds` answer; a test that must prove "no ML call" uses a
transport that fails the test on any request.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import missed_feeds, settings_store
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.workers import registry
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers import ml_publications as handlers
from app.workers.runtime import WorkerRuntime
from tests.services.ml_publications.conftest import missed_body

pytestmark = pytest.mark.postgres

HANDLER_NAME = "ml_publications.missed_feeds"
IDS = {"MLA3510103662", "MLA4010366978", "MLA1854370497"}


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


class MissedTransport(httpx.BaseTransport):
    """The captured first page at offset 0, the captured empty page elsewhere; `status` overrides every answer;
    `after_call` runs after each request (to flip a flag mid-run)."""

    def __init__(self, status: int = 200, after_call=None) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.after_call = after_call

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.after_call:
            self.after_call(len(self.requests))
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "boom"})
        offset = int(request.url.params.get("offset", 0))
        return httpx.Response(200, json=missed_body("items") if offset == 0 else missed_body("empty"))

    def offsets(self) -> list[int]:
        return [int(r.url.params.get("offset", 0)) for r in self.requests]


def make_handler(transport: httpx.BaseTransport) -> handlers.MissedFeedsHandler:
    def factory(pacer: Pacer) -> MlHttpClient:
        return MlHttpClient(
            pacer=pacer, transport=transport, token_loader=lambda: {"access_token": "t", "expires_epoch": 9e12}
        )

    return handlers.MissedFeedsHandler(client_factory=factory, pacer=Pacer(clock=FakeClock()))


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
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "7211863044554429")
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    return mlpub_pg


def sql_all(engine, statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).mappings().all()


def sql_scalar(engine, statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).scalar()


def enable() -> None:
    settings_store.set_setting("missed_feeds.enabled", True, "test")


def detail_of(engine) -> dict:
    return sql_scalar(engine, "SELECT detail FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)


def queued(engine) -> set:
    return {r["entity_id"] for r in sql_all(engine, "SELECT entity_id FROM ml_pub_refresh_queue")}


class TestWiring:
    def test_it_runs_every_two_hours_with_no_daily_slot_no_catch_up_and_no_notify(self) -> None:
        handler = handlers.missed_feeds
        assert handler.name == HANDLER_NAME
        assert handler.interval == timedelta(hours=2)
        assert handler.run_at_local is None and handler.channels == ()
        assert getattr(handler, "catch_up_interval", None) is None

    def test_it_is_registered_in_the_ml_worker_registry(self) -> None:
        assert handlers.missed_feeds in registry.ML_PUBLICATIONS_REGISTRY

    def test_it_shares_the_global_pacer_of_the_refresh_handler(self) -> None:
        assert handlers.missed_feeds.pacer is handlers.refresh.pacer

    def test_the_new_modules_add_no_cron_timer_or_notify(self) -> None:
        for path in (Path(handlers.__file__), Path(missed_feeds.__file__)):
            source = path.read_text(encoding="utf-8")
            assert not re.findall(r"crontab|OnCalendar|\.timer\b|pg_notify|\bLISTEN\b|\bNOTIFY\b", source), path


class TestDisabledOutcome:
    def test_the_flag_off_makes_no_call_and_no_write_and_reports_disabled(self, env) -> None:
        transport = NoCallTransport()
        result = make_handler(transport).run(context())

        assert result == JobResult(success=False, detail={"disabled": True})
        assert transport.requests == []
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_job_runs") == 0
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_refresh_queue") == 0
        assert sql_scalar(env, "SELECT count(*) FROM worker_job_state") == 0

    def test_the_kill_switch_overrides_an_enabled_row(self, env, monkeypatch) -> None:
        enable()
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)
        assert make_handler(NoCallTransport()).run(context()).detail == {"disabled": True}

    @pytest.mark.parametrize("other", ["sweep.enabled", "scan.enabled", "intake.enabled", "refresh.enabled"])
    def test_no_other_flag_turns_it_on(self, env, other) -> None:
        settings_store.set_setting(other, True, "test")
        assert make_handler(NoCallTransport()).run(context()).detail == {"disabled": True}

    def test_the_runtime_keeps_it_due_so_enabling_it_runs_it_on_the_next_pass(self, env) -> None:
        handler = make_handler(NoCallTransport())
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)

        assert runtime._run_handler(handler, now) is False

        row = sql_all(env, "SELECT * FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)[0]
        assert row["last_run_at"] is not None and row["last_success_at"] is None
        assert runtime._due_handlers(now + timedelta(seconds=10)) == [handler]


class TestRun:
    def test_an_enabled_run_enqueues_the_missed_items_and_records_the_run(self, env) -> None:
        enable()
        transport = MissedTransport()
        result = make_handler(transport).run(context())

        assert result.success is True and result.error is None
        assert queued(env) == IDS
        assert sql_scalar(env, "SELECT DISTINCT lane FROM ml_pub_refresh_queue") == 2
        assert [r["topic"] for r in map(lambda r: dict(r.url.params), transport.requests)] == ["items", "items"]
        record = sql_all(env, "SELECT * FROM ml_pub_job_runs")[0]
        assert record["job"] == "missed_feeds" and record["outcome"] == "success"

    def test_the_run_flushes_its_detail_with_the_per_endpoint_request_counters(self, env) -> None:
        enable()
        make_handler(MissedTransport()).run(context())
        detail = detail_of(env)
        assert detail["complete"] is True and detail["enqueued"] == 3 and detail["failures"] == 0
        assert detail["counters"]["missed_feeds"] == {"2xx": 2}
        assert detail["resume"] is None

    def test_topics_follow_the_intake_topics_setting(self, env) -> None:
        enable()
        settings_store.set_setting(
            "intake.topics",
            {
                "items": {"kind": "item", "resources": ["bundle"]},
                "items_prices": {"kind": "item", "resources": ["prices"]},
            },
            "test",
        )
        transport = MissedTransport()
        make_handler(transport).run(context())
        assert {r.url.params["topic"] for r in transport.requests} == {"items", "items_prices"}

    def test_a_missing_client_id_blocks_without_a_call_until_the_setup_is_fixed(self, env, monkeypatch) -> None:
        enable()
        monkeypatch.setattr(settings, "ML_CLIENT_ID", None)
        transport = NoCallTransport()
        result = make_handler(transport).run(context())
        assert result.success is True and result.detail["blocked"] == "client_not_configured"
        assert transport.requests == []

    def test_a_gap_beyond_48_hours_requests_the_scan_through_the_runtime_flag(self, env) -> None:
        enable()
        with env.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_pub_job_runs (job, started_at, finished_at, outcome, counts) "
                    "VALUES ('missed_feeds', now() - interval '3 days', now() - interval '3 days', 'success', '{}')"
                )
            )
        make_handler(MissedTransport()).run(context())
        assert sql_scalar(env, "SELECT state FROM worker_job_state WHERE name = 'ml_publications.scan'") == "requested"
        assert "coverage_gap" in sql_all(env, "SELECT counts FROM ml_pub_job_runs ORDER BY id DESC")[0]["counts"]


class TestRetryWithBackoff:
    def test_the_delay_doubles_from_a_minute_up_to_an_hour(self) -> None:
        delays = [handlers.missed_feeds_retry_delay(n).total_seconds() for n in (1, 2, 3, 4, 7, 20)]
        assert delays == [60, 120, 240, 480, 3600, 3600]

    @pytest.mark.parametrize("failures", [41, 42, 100, 10**6])
    def test_the_delay_stays_at_the_cap_however_many_failures_piled_up(self, failures) -> None:
        assert handlers.missed_feeds_retry_delay(failures) == handlers.MISSED_FEEDS_RETRY_CAP

    def test_a_run_with_a_huge_stored_failure_count_still_backs_off(self, env) -> None:
        enable()
        with env.begin() as conn:
            conn.execute(
                text("INSERT INTO worker_job_state (name, detail) VALUES (:n, CAST(:d AS jsonb))"),
                {"n": HANDLER_NAME, "d": '{"failures": 100}'},
            )
        result = make_handler(MissedTransport(status=403)).run(context())
        detail = detail_of(env)
        assert result.success is False and detail["failures"] == 101
        assert datetime.fromisoformat(detail["retry_at"]) > datetime.now(timezone.utc)

    def test_a_failed_run_is_not_retried_before_its_delay(self, env) -> None:
        enable()
        transport = MissedTransport(status=503)
        handler = make_handler(transport)

        first = handler.run(context())
        assert first.success is False and first.error == "http_503"
        assert len(transport.requests) == 1
        detail = detail_of(env)
        assert detail["failures"] == 1 and detail["resume"] == {"topic": "items", "offset": 0}
        assert datetime.fromisoformat(detail["retry_at"]) > datetime.now(timezone.utc)

        again = handler.run(context())  # the runtime would call it again on the very next pass
        assert again.success is False and "backoff_until" in again.detail
        assert len(transport.requests) == 1  # no call inside the delay
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_job_runs") == 1  # no record for a skipped pass

    def test_after_the_delay_it_retries_from_the_failed_page_and_a_success_clears_the_streak(self, env) -> None:
        enable()
        handler = make_handler(MissedTransport(status=503))
        handler.run(context())
        with env.begin() as conn:  # the delay passed
            conn.execute(
                text(
                    "UPDATE worker_job_state SET detail = jsonb_set(detail, '{retry_at}', to_jsonb(CAST(:past AS text)))"
                ),
                {"past": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},
            )
        good = MissedTransport()
        handler = make_handler(good)
        result = handler.run(context())
        assert result.success is True
        detail = detail_of(env)
        assert detail["failures"] == 0 and detail["retry_at"] is None
        assert queued(env) == IDS

    def test_consecutive_failures_lengthen_the_delay(self, env) -> None:
        enable()
        handler = make_handler(MissedTransport(status=500))
        handler.run(context())
        first = datetime.fromisoformat(detail_of(env)["retry_at"])
        with env.begin() as conn:
            conn.execute(
                text(
                    "UPDATE worker_job_state SET detail = jsonb_set(detail, '{retry_at}', to_jsonb(CAST(:past AS text)))"
                ),
                {"past": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},
            )
        handler.run(context())
        detail = detail_of(env)
        assert detail["failures"] == 2
        assert datetime.fromisoformat(detail["retry_at"]) - first > timedelta(seconds=30)

    def test_a_rate_limit_waits_without_counting_as_a_failure(self, env) -> None:
        enable()
        result = make_handler(MissedTransport(status=429)).run(context())
        detail = detail_of(env)
        assert result.success is False and detail["failures"] == 0 and detail["stopped"] == "rate_limited"
        assert datetime.fromisoformat(detail["retry_at"]) > datetime.now(timezone.utc)

    def test_a_401_blocks_until_the_setup_is_fixed_instead_of_retrying(self, env) -> None:
        enable()
        result = make_handler(MissedTransport(status=401)).run(context())
        assert result.success is True and result.detail["blocked"] == "unauthorized"


class TestResume:
    def test_a_flag_turned_off_mid_run_keeps_the_position_and_the_next_run_continues_there(self, env) -> None:
        enable()

        def off_after_first_call(n: int) -> None:
            if n == 1:
                settings_store.set_setting("missed_feeds.enabled", False, "test")

        first = MissedTransport(after_call=off_after_first_call)
        result = make_handler(first).run(context())
        assert result.success is False and first.offsets() == [0]
        assert detail_of(env)["resume"] == {"topic": "items", "offset": missed_feeds.PAGE_LIMIT}
        assert queued(env) == IDS

        enable()
        second = MissedTransport()
        assert make_handler(second).run(context()).success is True
        assert second.offsets() == [missed_feeds.PAGE_LIMIT]
        assert detail_of(env)["resume"] is None

    def test_a_position_older_than_the_limit_is_dropped_because_the_list_moved_meanwhile(self, env) -> None:
        enable()
        with env.begin() as conn:
            conn.execute(
                text("INSERT INTO worker_job_state (name, detail) VALUES (:n, CAST(:d AS jsonb))"),
                {
                    "n": HANDLER_NAME,
                    "d": '{"resume": {"topic": "items", "offset": 40}, "resume_at": "%s"}'
                    % (
                        datetime.now(timezone.utc) - handlers.MISSED_FEEDS_RESUME_MAX_AGE - timedelta(minutes=1)
                    ).isoformat(),
                },
            )
        transport = MissedTransport()
        make_handler(transport).run(context())
        assert transport.offsets()[0] == 0

    def test_a_recent_position_is_kept(self, env) -> None:
        enable()
        with env.begin() as conn:
            conn.execute(
                text("INSERT INTO worker_job_state (name, detail) VALUES (:n, CAST(:d AS jsonb))"),
                {
                    "n": HANDLER_NAME,
                    "d": '{"resume": {"topic": "items", "offset": 40}, "resume_at": "%s"}'
                    % (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                },
            )
        transport = MissedTransport()
        make_handler(transport).run(context())
        assert transport.offsets()[0] == 40

    def test_a_chain_of_failing_runs_does_not_keep_a_position_alive_past_the_limit(self, env) -> None:
        enable()
        started = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with env.begin() as conn:
            conn.execute(
                text("INSERT INTO worker_job_state (name, detail) VALUES (:n, CAST(:d AS jsonb))"),
                {"n": HANDLER_NAME, "d": '{"resume": {"topic": "items", "offset": 40}, "resume_at": "%s"}' % started},
            )
        make_handler(MissedTransport(status=503)).run(context())  # fails at offset 40: the chain keeps its start
        assert detail_of(env)["resume_at"] == started

    def test_a_corrupt_failure_count_in_the_stored_state_does_not_stop_the_run(self, env) -> None:
        enable()
        with env.begin() as conn:
            conn.execute(
                text("INSERT INTO worker_job_state (name, detail) VALUES (:n, CAST(:d AS jsonb))"),
                {"n": HANDLER_NAME, "d": '{"failures": "many", "resume": "nope", "resume_at": 5}'},
            )
        transport = MissedTransport(status=503)
        result = make_handler(transport).run(context())
        assert result.error == "http_503" and detail_of(env)["failures"] == 1
        assert transport.offsets() == [0]

    def test_an_exhausted_deadline_is_continued_on_the_next_pass_without_waiting(self, env) -> None:
        enable()
        transport = MissedTransport()
        result = make_handler(transport).run(context(seconds=-1))
        assert result.success is False and transport.requests == []
        detail = detail_of(env)
        assert detail["stopped"] == "deadline" and detail["resume"]["offset"] == 0
        assert detail["retry_at"] is None  # no delay: the deadline is not a failure
