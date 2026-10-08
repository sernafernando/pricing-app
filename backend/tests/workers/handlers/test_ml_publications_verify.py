"""`ml_publications.verify` (design D17): the daily 05:00 job with a 2 minute catch-up, each sub-job under its own flag.

Postgres only. The ML side is the real client over a mock transport serving captured item bodies; a test that
must prove "no ML call" uses a transport that fails the test on any request.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import admin, settings_store, verification
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.workers import registry
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers import ml_publications as handlers
from app.workers.scheduling import is_due
from tests.services.ml_publications.test_verification import FakeClock, MlTransport, seed

pytestmark = pytest.mark.postgres

HANDLER_NAME = "ml_publications.verify"


class NoCallTransport(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unexpected ML call: {request.url}")


def make_handler(transport: httpx.BaseTransport) -> handlers.VerifyHandler:
    def factory(pacer: Pacer) -> MlHttpClient:
        return MlHttpClient(
            pacer=pacer, transport=transport, token_loader=lambda: {"access_token": "t", "expires_epoch": 9e12}
        )

    return handlers.VerifyHandler(client_factory=factory, pacer=Pacer(clock=FakeClock()))


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


def runs(engine) -> dict:
    return {r["job"]: r for r in sql_all(engine, "SELECT * FROM ml_pub_job_runs")}


class TestWiring:
    def test_it_runs_daily_at_five_with_a_two_minute_catch_up_and_no_notify(self) -> None:
        handler = handlers.verify
        assert handler.name == HANDLER_NAME
        assert handler.run_at_local == time(5, 0) and handler.interval is None
        assert handler.catch_up_interval == timedelta(minutes=2)
        assert handler.channels == ()

    def test_it_is_the_last_ml_publications_handler_of_the_ml_worker_registry(self) -> None:
        ours = [h for h in registry.ML_PUBLICATIONS_REGISTRY if h.name.startswith("ml_publications.")]
        assert ours[-1] is handlers.verify

    def test_the_verification_module_adds_no_cron_timer_or_notify(self) -> None:
        source = Path(verification.__file__).read_text(encoding="utf-8")
        assert not re.findall(r"crontab|OnCalendar|\.timer\b|pg_notify|\bLISTEN\b|\bNOTIFY\b", source)

    def test_both_flags_are_in_the_allow_list_and_default_off(self) -> None:
        for key in ("verify.enabled", "divergence.enabled"):
            assert key in settings_store.SETTING_DEFS
            assert settings_store.get_setting(key).value is False

    def test_the_admin_surface_knows_the_job_and_both_flags(self) -> None:
        assert admin.JOBS["verify"] == (HANDLER_NAME, "verify.enabled")
        assert admin.JOBS["divergence"] == (HANDLER_NAME, "divergence.enabled")
        assert admin.FLAG_HANDLER["verify.enabled"] == admin.FLAG_HANDLER["divergence.enabled"] == HANDLER_NAME


class TestFlagsAreIndependent:
    def test_both_off_does_nothing_and_keeps_the_slot(self, env) -> None:
        seed(env, {"active": 3})
        handler = make_handler(NoCallTransport())

        result = handler.run(context())

        assert result == JobResult(success=False, detail={"disabled": True})
        assert runs(env) == {}
        # not a success, so `last_success_at` stays old and the daily slot is still due: enabling later runs it
        after_slot = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
        assert is_due(handler, now=after_slot, last_success_at=None, incomplete=False) is True

    def test_the_kill_switch_overrides_enabled_rows(self, env, monkeypatch) -> None:
        settings_store.set_setting("verify.enabled", True, "test")
        settings_store.set_setting("divergence.enabled", True, "test")
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)

        assert make_handler(NoCallTransport()).run(context()).detail == {"disabled": True}
        assert runs(env) == {}

    def test_verify_alone_writes_the_snapshot_and_makes_no_ml_call(self, env) -> None:
        seed(env, {"active": 3})
        settings_store.set_setting("verify.enabled", True, "test")

        result = make_handler(NoCallTransport()).run(context())

        assert result.success is True
        assert set(runs(env)) == {"freshness"}
        assert runs(env)["freshness"]["counts"]["items"]["total"] == 3

    def test_divergence_alone_samples_and_writes_no_snapshot(self, env) -> None:
        fresh = seed(env, {"active": 4, "paused": 2})
        settings_store.set_setting("divergence.enabled", True, "test")
        transport = MlTransport(fresh)

        result = make_handler(transport).run(context())

        assert result.success is True and result.detail["divergence"]["rate"] == 100.0 and len(transport.requests) == 1
        assert set(runs(env)) == {"divergence"}

    def test_both_on_writes_both_records(self, env) -> None:
        fresh = seed(env, {"active": 4})
        settings_store.set_setting("verify.enabled", True, "test")
        settings_store.set_setting("divergence.enabled", True, "test")

        result = make_handler(MlTransport(fresh)).run(context())

        assert result.success is True and set(runs(env)) == {"divergence", "freshness"}
        assert result.detail["snapshot"]["outcome"] == "success"
        assert result.detail["divergence"]["rate"] == 100.0

    def test_the_sample_size_comes_from_the_setting_of_the_environment(self, env, monkeypatch) -> None:
        fresh = seed(env, {"active": 30})
        monkeypatch.setattr(settings, "ML_PUB_DIVERGENCE_SAMPLE_SIZE", 7)
        settings_store.set_setting("divergence.enabled", True, "test")

        assert make_handler(MlTransport(fresh)).run(context()).detail["divergence"]["sampled"] == 7


class TestOutcomes:
    def test_a_flagged_run_is_a_finished_run_with_the_flag_in_its_record(self, env) -> None:
        fresh = seed(env, {"active": 10})
        fresh[sorted(fresh)[0]]["status"] = "paused"  # one field of a captured body
        settings_store.set_setting("divergence.enabled", True, "test")

        result = make_handler(MlTransport(fresh)).run(context())

        assert result.success is True  # the check ran; the finding is in the record, not a handler failure
        assert result.detail["divergence"]["below_target"] is True
        assert runs(env)["divergence"]["outcome"] == "below_target"

    def test_a_failed_check_is_recorded_and_does_not_hot_loop(self, env) -> None:
        fresh = seed(env, {"active": 3})
        settings_store.set_setting("divergence.enabled", True, "test")

        result = make_handler(MlTransport(fresh, status=500)).run(context())

        assert result.success is True and "500" in str(result.error)
        assert "500" in result.detail["error"]  # where the status report's `jobs[].last_error` reads it
        assert runs(env)["divergence"]["outcome"] == "failed"

    def test_an_interrupted_check_is_incomplete_not_failed_and_runs_no_snapshot(self, env) -> None:
        fresh = seed(env, {"active": 3})
        settings_store.set_setting("divergence.enabled", True, "test")
        settings_store.set_setting("verify.enabled", True, "test")

        result = make_handler(MlTransport(fresh, status=429)).run(context())

        # a success with `complete: False`: the runtime then unlocks the 2 minute catch-up, and the status report
        # does not show the handler as failing because the check yielded or waited out a 429
        assert result.success is True and result.detail["complete"] is False
        assert result.detail["divergence"]["interruption"] == "rate_limited"
        assert runs(env) == {}

    def test_the_catch_up_makes_an_incomplete_check_due_two_minutes_after_its_last_success(self, env) -> None:
        handler = handlers.verify
        last = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)  # 06:00 local: today's slot already ran
        assert is_due(handler, now=last + timedelta(seconds=90), last_success_at=last, incomplete=True) is False
        assert is_due(handler, now=last + timedelta(minutes=2), last_success_at=last, incomplete=True) is True
        assert is_due(handler, now=last + timedelta(minutes=5), last_success_at=last, incomplete=False) is False

    def test_a_finished_check_marks_the_run_complete(self, env) -> None:
        fresh = seed(env, {"active": 3})
        settings_store.set_setting("divergence.enabled", True, "test")

        assert make_handler(MlTransport(fresh)).run(context()).detail["complete"] is True

    def test_a_missing_seller_is_a_recorded_failure_not_an_exception(self, env, monkeypatch) -> None:
        fresh = seed(env, {"active": 3})
        monkeypatch.setattr(settings, "ML_USER_ID", "")
        settings_store.set_setting("divergence.enabled", True, "test")

        result = make_handler(MlTransport(fresh)).run(context())

        assert result.success is True and runs(env)["divergence"]["outcome"] == "failed"
