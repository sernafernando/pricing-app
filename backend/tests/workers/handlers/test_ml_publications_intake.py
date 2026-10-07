"""`ml_publications.intake` (design D13, D17): the handler around the intake core.

Postgres only. The bridge is a second throwaway schema holding the real `webhook_latest` DDL, rows
are real captured ones (only `received_at`/`resource` changed to sit on a test timeline).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import settings_store
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers import ml_publications as handlers
from app.workers.runtime import WorkerRuntime
from tests.services.ml_publications.conftest import put_webhook, webhook_row
from tests.workers.handlers.test_ml_publications_refresh import (
    NoCallTransport,
    ScriptedTransport,
    bulk_responder,
    context,
    make_handler,
    sql_all,
    sql_one,
    sql_scalar,
)

pytestmark = pytest.mark.postgres

HANDLER_NAME = "ml_publications.intake"
SELLER = "413658225"


def recent(seconds_ago: float) -> str:
    return str(datetime.now(timezone.utc) - timedelta(seconds=seconds_ago))


def item_row(item_id: str, seconds_ago: float):
    """Real captured `items` row (real payload, resource and received_at changed)."""
    return webhook_row("items", 0, resource=f"/items/{item_id}", received_at=recent(seconds_ago))


class CountingBridge:
    """Hands out the bridge engine and counts how often the handler asked for it."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.engine


@pytest.fixture()
def env(mlpub_pg, bridge_pg, monkeypatch):
    with mlpub_pg.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE worker_job_state (name varchar(64) PRIMARY KEY, last_run_at timestamptz, "
                "last_success_at timestamptz, state varchar(32), detail jsonb, heartbeat_at timestamptz)"
            )
        )
    monkeypatch.setattr(settings, "ML_USER_ID", SELLER)
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "1")
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    bridge = CountingBridge(bridge_pg)
    return mlpub_pg, bridge_pg, bridge


def counters(pricing) -> dict:
    return sql_scalar(pricing, "SELECT detail FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)["counters"]


def queued_ids(pricing) -> list[str]:
    return [r["entity_id"] for r in sql_all(pricing, "SELECT entity_id FROM ml_pub_refresh_queue ORDER BY 1")]


class TestDisabledOutcome:
    def test_flag_off_reads_no_bridge_writes_nothing_and_reports_disabled(self, env) -> None:
        pricing, bridge_pg, bridge = env
        put_webhook(bridge_pg, item_row("MLA935110613", 5))
        result = handlers.IntakeHandler(bridge_engine=bridge).run(context())

        assert result == JobResult(success=False, detail={"disabled": True})
        assert bridge.calls == 0
        assert sql_scalar(pricing, "SELECT count(*) FROM ml_pub_intake_cursors") == 0
        assert sql_scalar(pricing, "SELECT count(*) FROM ml_pub_refresh_queue") == 0
        assert sql_scalar(pricing, "SELECT count(*) FROM worker_job_state") == 0

    def test_the_kill_switch_overrides_a_db_enabled_row(self, env, monkeypatch) -> None:
        _pricing, _bridge_pg, bridge = env
        settings_store.set_setting("intake.enabled", True, "test")
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)

        result = handlers.IntakeHandler(bridge_engine=bridge).run(context())

        assert result == JobResult(success=False, detail={"disabled": True})
        assert bridge.calls == 0

    def test_the_runtime_keeps_a_disabled_intake_due(self, env) -> None:
        handler = handlers.IntakeHandler(bridge_engine=env[2])
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        now = datetime.now(timezone.utc)

        assert runtime._run_handler(handler, now) is False

        row = sql_one(env[0], "SELECT * FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)
        assert row["last_success_at"] is None
        assert runtime._due_handlers(now) == [handler]


class TestIntakeOnRefreshOff:
    def test_intake_only_enqueues_makes_no_ml_call_and_loses_nothing_when_refresh_is_enabled(self, env) -> None:
        pricing, bridge_pg, bridge = env
        settings_store.set_setting("intake.enabled", True, "test")
        put_webhook(bridge_pg, item_row("MLA935110613", 5))
        put_webhook(bridge_pg, item_row("MLA934406852", 4))
        # The very first run only creates the cursor at now - overlap; both rows are inside the window.
        intake = handlers.IntakeHandler(bridge_engine=bridge)

        result = intake.run(context())

        assert result.success is True
        assert queued_ids(pricing) == ["MLA934406852", "MLA935110613"]
        no_calls = NoCallTransport()
        refresh_off = make_handler(no_calls).run(context())  # refresh.enabled is still off
        assert refresh_off == JobResult(success=False, detail={"disabled": True})
        assert no_calls.requests == [] and queued_ids(pricing) == ["MLA934406852", "MLA935110613"]

        settings_store.set_setting("refresh.enabled", True, "test")
        transport = ScriptedTransport(bulk_responder)
        assert make_handler(transport).run(context()).success is True
        assert sorted(transport.ids()[0]) == ["MLA934406852", "MLA935110613"]
        assert queued_ids(pricing) == []
        stored = {r["item_id"] for r in sql_all(pricing, "SELECT item_id FROM ml_items")}
        assert stored == {"MLA934406852", "MLA935110613"}

    def test_default_settings_read_only_the_items_topic(self, env) -> None:
        pricing, bridge_pg, bridge = env
        settings_store.set_setting("intake.enabled", True, "test")
        put_webhook(bridge_pg, item_row("MLA935110613", 5))
        put_webhook(bridge_pg, webhook_row("items_prices", 0, received_at=recent(5)))
        put_webhook(bridge_pg, webhook_row("price_suggestion", 0, received_at=recent(5)))

        handlers.IntakeHandler(bridge_engine=bridge).run(context())

        assert queued_ids(pricing) == ["MLA935110613"]
        assert sql_scalar(pricing, "SELECT count(*) FROM ml_pub_intake_cursors") == 1


class TestRunBounds:
    def test_a_deadline_in_the_past_reads_nothing_from_the_bridge_rows(self, env) -> None:
        pricing, bridge_pg, bridge = env
        settings_store.set_setting("intake.enabled", True, "test")
        put_webhook(bridge_pg, item_row("MLA935110613", 5))
        expired = WorkerContext(deadline=datetime.now(timezone.utc) - timedelta(seconds=1), worker_name="worker-ml")

        result = handlers.IntakeHandler(bridge_engine=bridge).run(expired)

        assert result.success is True
        assert queued_ids(pricing) == []

    def test_turning_the_flag_off_mid_run_stops_at_the_next_batch_boundary(self, env, monkeypatch) -> None:
        pricing, bridge_pg, bridge = env
        settings_store.set_setting("intake.enabled", True, "test")
        monkeypatch.setattr(settings, "ML_PUB_INTAKE_BATCH", 1)
        # Cursor already stored 60 s back, so the three rows below are all forward-pass rows.
        handlers.IntakeHandler(bridge_engine=bridge).run(context())
        for n, item in enumerate(("MLA1000000001", "MLA1000000002", "MLA1000000003")):
            put_webhook(bridge_pg, item_row(item, 3 - n))
        reads = {"n": 0}

        def flag_off_during_the_first_batch():
            reads["n"] += 1
            if reads["n"] == 1:  # the operator flips the flag while batch 1 is being read
                settings_store.set_setting("intake.enabled", False, "test")
            return bridge_pg

        result = handlers.IntakeHandler(bridge_engine=flag_off_during_the_first_batch).run(context())

        assert result.success is True
        assert queued_ids(pricing) == ["MLA1000000001"]
        # nothing was skipped: the next enabled run resumes from the stored cursor
        settings_store.set_setting("intake.enabled", True, "test")
        monkeypatch.setattr(settings, "ML_PUB_INTAKE_BATCH", 1000)
        handlers.IntakeHandler(bridge_engine=bridge).run(context())
        assert queued_ids(pricing) == ["MLA1000000001", "MLA1000000002", "MLA1000000003"]

    def test_an_unreachable_bridge_returns_a_failure_without_raising(self, env) -> None:
        settings_store.set_setting("intake.enabled", True, "test")

        def unreachable():
            raise RuntimeError("ML_WEBHOOK_DB_URL is not configured")

        result = handlers.IntakeHandler(bridge_engine=unreachable).run(context())

        assert result.success is False and result.error == "bridge_unavailable"

    def test_a_missing_seller_id_fails_closed(self, env, monkeypatch) -> None:
        _pricing, _bridge_pg, bridge = env
        settings_store.set_setting("intake.enabled", True, "test")
        monkeypatch.setattr(settings, "ML_USER_ID", None)

        result = handlers.IntakeHandler(bridge_engine=bridge).run(context())

        assert result.success is False and result.error == "seller_not_configured"
        assert bridge.calls == 0


class TestCounters:
    def test_cumulative_counters_are_flushed_into_worker_job_state(self, env) -> None:
        pricing, bridge_pg, bridge = env
        settings_store.set_setting("intake.enabled", True, "test")
        foreign = item_row("MLA1100000001", 6)
        foreign["payload"]["user_id"] = 999  # real payload, one field changed
        put_webhook(bridge_pg, foreign)
        put_webhook(bridge_pg, item_row("MLA1100000002", 5))
        intake = handlers.IntakeHandler(bridge_engine=bridge)

        intake.run(context())
        first = counters(pricing)
        put_webhook(bridge_pg, item_row("MLA1100000003", 1))
        intake.run(context())
        second = counters(pricing)

        assert first["rows_read"] == 2 and first["enqueued"] == 1 and first["skipped_foreign_seller"] == 1
        assert second["rows_read"] == 3 and second["enqueued"] == 2
        detail = sql_scalar(pricing, "SELECT detail FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)
        assert detail["last_run"]["rows_read"] == 1 and "at" in detail["last_run"]

    def test_an_idle_run_writes_no_counters(self, env) -> None:
        pricing, _bridge_pg, bridge = env
        settings_store.set_setting("intake.enabled", True, "test")

        handlers.IntakeHandler(bridge_engine=bridge).run(context())

        assert sql_scalar(pricing, "SELECT count(*) FROM worker_job_state") == 0
