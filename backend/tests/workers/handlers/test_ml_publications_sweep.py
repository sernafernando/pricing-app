"""`ml_publications.sweep` (design D17): the 10-minute interval tick, its own flag, no ML call of its own.

Postgres only. The sweep enqueues; the refresh handler fetches, so nothing here may reach ML.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import settings_store, sweeps
from app.services.ml_publications.ml_http import MlHttpClient
from app.workers import registry
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers import ml_publications as handlers
from app.workers.runtime import WorkerRuntime

pytestmark = pytest.mark.postgres

HANDLER_NAME = "ml_publications.sweep"


def context() -> WorkerContext:
    return WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="worker-ml")


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
    with mlpub_pg.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE worker_job_state (name varchar(64) PRIMARY KEY, last_run_at timestamptz, "
                "last_success_at timestamptz, state varchar(32), detail jsonb, heartbeat_at timestamptz)"
            )
        )
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)

    def no_ml(*args, **kwargs):
        pytest.fail("the sweep must not call ML")

    monkeypatch.setattr(MlHttpClient, "get", no_ml)
    return mlpub_pg


def sql_all(engine, statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).mappings().all()


def sql_scalar(engine, statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).scalar()


def put_item(engine, item_id: str, status: str = "active") -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO ml_items (item_id, status, http_status, last_checked_at) VALUES (:i, :s, 200, now())"),
            {"i": item_id, "s": status},
        )


def enable(**other) -> None:
    settings_store.set_setting("sweep.enabled", True, "test")
    settings_store.set_setting("bundle_resources", ["core", "performance", "visits"], "test")
    for key, value in other.items():
        settings_store.set_setting(key.replace("__", "."), value, "test")


def queued(engine) -> dict:
    return {
        r["entity_id"]: (r["lane"], list(r["resources"])) for r in sql_all(engine, "SELECT * FROM ml_pub_refresh_queue")
    }


class TestWiring:
    def test_it_runs_every_ten_minutes_with_no_daily_slot_and_no_notify(self) -> None:
        handler = handlers.sweep
        assert handler.name == HANDLER_NAME
        assert handler.interval == timedelta(minutes=10)
        assert handler.run_at_local is None and handler.channels == ()
        assert getattr(handler, "catch_up_interval", None) is None

    def test_the_interval_is_what_the_batch_size_assumes(self) -> None:
        assert handlers.sweep.interval * sweeps.TICKS_PER_DAY == timedelta(days=1)

    def test_it_is_registered_in_the_ml_worker_registry(self) -> None:
        assert handlers.sweep in registry.ML_PUBLICATIONS_REGISTRY

    def test_the_handler_module_adds_no_cron_timer_or_notify(self) -> None:
        for path in (Path(handlers.__file__), Path(sweeps.__file__)):
            source = path.read_text(encoding="utf-8")
            assert not re.findall(r"crontab|OnCalendar|\.timer\b|pg_notify|\bLISTEN\b|\bNOTIFY\b", source), path


class TestFlagsAreIndependent:
    def test_the_flag_off_does_nothing_and_reports_disabled(self, env) -> None:
        put_item(env, "MLA1")
        settings_store.set_setting("bundle_resources", ["core", "performance", "visits"], "test")
        result = handlers.sweep.run(context())

        assert result == JobResult(success=False, detail={"disabled": True})
        assert queued(env) == {}
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_job_runs") == 0
        assert sql_scalar(env, "SELECT count(*) FROM worker_job_state") == 0

    def test_the_kill_switch_overrides_an_enabled_row(self, env, monkeypatch) -> None:
        enable()
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)
        assert handlers.sweep.run(context()).detail == {"disabled": True}

    @pytest.mark.parametrize("other", ["missed_feeds.enabled", "scan.enabled", "refresh.enabled", "intake.enabled"])
    def test_no_other_flag_turns_the_sweep_on(self, env, other) -> None:
        settings_store.set_setting(other, True, "test")
        settings_store.set_setting("bundle_resources", ["core", "performance", "visits"], "test")
        put_item(env, "MLA1")
        assert handlers.sweep.run(context()).detail == {"disabled": True}
        assert queued(env) == {}

    def test_the_sweep_flag_does_not_turn_missed_feeds_on(self, env) -> None:
        enable()
        assert handlers.missed_feeds.run(context()).detail == {"disabled": True}

    def test_the_runtime_keeps_a_disabled_sweep_due_so_enabling_it_runs_it_on_the_next_pass(self, env) -> None:
        runtime = WorkerRuntime(registry=[handlers.sweep], direct_url=None)
        now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
        assert runtime._run_handler(handlers.sweep, now) is False
        row = sql_all(env, "SELECT * FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)[0]
        assert row["last_run_at"] is not None and row["last_success_at"] is None
        assert runtime._due_handlers(now + timedelta(seconds=10)) == [handlers.sweep]


class TestTick:
    def test_an_enabled_tick_enqueues_the_oldest_items_by_name_and_records_the_run(self, env) -> None:
        put_item(env, "MLA1")
        enable()
        result = handlers.sweep.run(context())

        assert result.success is True and result.error is None
        assert queued(env) == {"MLA1": (4, ["performance", "visits"])}
        detail = sql_scalar(env, "SELECT detail FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)
        assert detail["outcome"] == "success" and detail["enqueued"] == 2 and "at" in detail
        assert detail["resources"]["visits"] == {"eligible": 1, "batch": 1, "selected": 1}
        assert sql_all(env, "SELECT outcome FROM ml_pub_job_runs WHERE job = 'sweep'")[0]["outcome"] == "success"

    def test_the_default_bundle_resources_sweep_nothing_until_the_operator_lists_them(self, env) -> None:
        put_item(env, "MLA1")
        settings_store.set_setting("sweep.enabled", True, "test")  # bundle_resources stays ["core"]
        result = handlers.sweep.run(context())
        assert result.success is True and result.detail["outcome"] == "no_resources"
        assert queued(env) == {}

    def test_sweep_statuses_is_read_at_runtime_and_narrows_without_a_deploy(self, env) -> None:
        put_item(env, "MLA1", "active")
        put_item(env, "MLA2", "paused")
        enable()
        handlers.sweep.run(context())
        assert set(queued(env)) == {"MLA1"}  # K = 1 and both are never-checked: the item id breaks the tie
        with env.begin() as conn:
            conn.execute(text("DELETE FROM ml_pub_refresh_queue"))
        settings_store.set_setting("sweep.statuses", ["paused"], "test")
        handlers.sweep.run(context())
        assert set(queued(env)) == {"MLA2"}

    def test_the_not_applicable_recheck_interval_is_the_env_setting(self, env, monkeypatch) -> None:
        put_item(env, "MLA1")
        with env.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_item_performance (item_id, applicable, last_checked_at, http_status) "
                    "VALUES ('MLA1', false, now() - interval '10 days', 400)"
                )
            )
        enable(bundle_resources=["core", "performance"])
        handlers.sweep.run(context())
        assert queued(env) == {}
        monkeypatch.setattr(settings, "ML_PUB_NOT_APPLICABLE_RECHECK_DAYS", 7)
        handlers.sweep.run(context())
        assert queued(env) == {"MLA1": (4, ["performance"])}

    def test_a_failed_tick_is_reported_and_left_for_the_next_interval(self, env, monkeypatch) -> None:
        enable()
        failed = sweeps.SweepResult(outcome=sweeps.OUTCOME_FAILED, error="internal_error: RuntimeError: x")
        monkeypatch.setattr(sweeps, "run_sweep", lambda **kwargs: failed)
        result = handlers.sweep.run(context())
        assert result.success is True and result.error == "internal_error: RuntimeError: x"
        assert result.detail["outcome"] == "failed"
