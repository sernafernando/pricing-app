"""ml-sync-pipeline T5 (S5): how late the store is on what ML told it changed, per data class, and the queue lag
per lane; past the target the owner gets a WhatsApp.

A resource is late when a notification asked for it, it was not fetched since, and it has been due (the
notification, or its last check plus its minimum age, whichever is later) for longer than its target.

Postgres only. The handler measures; nothing here may reach ML.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.ml_publications import freshness, settings_store
from app.services.ml_publications.ml_http import MlHttpClient
from app.workers import registry
from app.workers.context import WorkerContext
from app.workers.handlers import ml_publications as handlers

pytestmark = pytest.mark.postgres

HANDLER_NAME = "ml_publications.freshness"


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
        pytest.fail("the freshness check must not call ML")

    monkeypatch.setattr(MlHttpClient, "get", no_ml)
    settings_store.set_setting("bundle_resources", ["core", "prices", "promotions", "competition"], "test")
    return mlpub_pg


@pytest.fixture()
def sent(monkeypatch) -> List[str]:
    messages: List[str] = []

    def send(message: str) -> str:
        messages.append(message)
        return "sent"

    monkeypatch.setattr(handlers.wabot_client, "send_to_owner", send)
    return messages


def run(engine, statement: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(statement), params)


def ago(minutes: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def put_item(engine, item_id: str, *, checked: datetime, catalog: bool = False, status: str = "active") -> None:
    run(
        engine,
        "INSERT INTO ml_items (item_id, status, http_status, last_checked_at, catalog_listing) "
        "VALUES (:i, :s, 200, :c, :cat)",
        i=item_id,
        s=status,
        c=checked,
        cat=catalog,
    )


def put_checked(engine, table: str, item_id: str, checked: datetime) -> None:
    run(
        engine,
        f"INSERT INTO {table} (item_id, http_status, last_checked_at) VALUES (:i, 200, :c)",
        i=item_id,
        c=checked,
    )


def notify(engine, item_id: str, *, received: datetime, resources=("bundle",), lane: int = 1) -> None:
    run(
        engine,
        "INSERT INTO ml_pub_refresh_queue (kind, entity_id, resources, lane, source_received_at) "
        "VALUES ('item', :i, CAST(:r AS text[]), :lane, :at)",
        i=item_id,
        r="{" + ",".join(resources) + "}",
        lane=lane,
        at=received,
    )


def measure(engine) -> dict:
    with engine.connect() as conn:
        return freshness.measure(Session(bind=conn))


class TestStatus:
    def test_a_notification_waiting_past_two_minutes_is_late(self, env) -> None:
        put_item(env, "MLA1", checked=ago(30))
        put_item(env, "MLA2", checked=ago(30))
        notify(env, "MLA1", received=ago(3))
        notify(env, "MLA2", received=ago(1))

        items = measure(env)["resources"]["items"]

        assert items["target_seconds"] == 120
        assert items["late"] == 1
        assert 170 < items["oldest_late_seconds"] < 200

    def test_an_item_not_in_the_store_yet_is_late_too(self, env) -> None:
        notify(env, "MLA9", received=ago(3))

        assert measure(env)["resources"]["items"]["late"] == 1


class TestCommercialData:
    def test_a_resource_fetched_since_the_notification_is_not_late(self, env) -> None:
        put_item(env, "MLA1", checked=ago(1))
        put_checked(env, "ml_item_prices", "MLA1", ago(1))
        notify(env, "MLA1", received=ago(10))

        assert measure(env)["resources"]["prices"]["late"] == 0

    def test_a_notification_for_promotions_only_never_makes_prices_late(self, env) -> None:
        put_item(env, "MLA1", checked=ago(30))
        put_checked(env, "ml_item_prices", "MLA1", ago(30))
        notify(env, "MLA1", received=ago(10), resources=("promotions",))

        resources = measure(env)["resources"]
        assert resources["prices"]["late"] == 0
        assert resources["promotions"]["late"] == 1

    def test_the_wait_of_the_minimum_age_is_not_late(self, env) -> None:
        # competition: minimum age 15 min, target 5 min. Checked 12 min ago: due in 3 min, not late.
        put_item(env, "MLA1", checked=ago(30), catalog=True)
        put_checked(env, "ml_item_competition", "MLA1", ago(12))
        notify(env, "MLA1", received=ago(10))
        # Checked 25 min ago: due since the notification, 10 min ago, past the 5 min target.
        put_item(env, "MLA2", checked=ago(30), catalog=True)
        put_checked(env, "ml_item_competition", "MLA2", ago(25))
        notify(env, "MLA2", received=ago(10))

        assert measure(env)["resources"]["competition"]["late"] == 1

    def test_competition_of_an_item_that_is_not_a_catalog_listing_is_not_measured(self, env) -> None:
        put_item(env, "MLA1", checked=ago(30), catalog=False)
        notify(env, "MLA1", received=ago(30))

        assert measure(env)["resources"]["competition"]["late"] == 0

    def test_a_resource_the_store_does_not_collect_is_not_measured(self, env) -> None:
        put_item(env, "MLA1", checked=ago(30))
        notify(env, "MLA1", received=ago(30))

        resources = measure(env)["resources"]
        assert "description" not in resources
        assert "stock" not in resources  # the publication's available quantity: no target (owner, 2026-10-27)


class TestVisits:
    def test_measured_only_while_the_sweep_collects_them(self, env) -> None:
        put_item(env, "MLA1", checked=ago(1))
        put_checked(env, "ml_item_visits", "MLA1", ago(60 * 30))
        settings_store.set_setting("bundle_resources", ["core", "visits"], "test")
        assert "visits" not in measure(env)["resources"]

        settings_store.set_setting("sweep.enabled", True, "test")
        visits = measure(env)["resources"]["visits"]
        assert visits["late"] == 1


class TestQueueLag:
    def test_the_oldest_wait_of_each_lane_is_reported(self, env) -> None:
        notify(env, "MLA1", received=ago(3), lane=2)

        lanes = {lane["lane"]: lane for lane in measure(env)["lanes"]}
        assert lanes[2]["waiting"] == 1
        assert lanes[1]["waiting"] == 0


class TestTheHandler:
    def test_it_is_a_one_minute_tick_of_worker_ml(self) -> None:
        assert handlers.freshness.name == HANDLER_NAME
        assert handlers.freshness.interval == timedelta(minutes=1)
        assert handlers.freshness.channels == ()
        assert handlers.freshness in registry.ML_PUBLICATIONS_REGISTRY

    def test_it_alerts_once_while_late_and_once_when_back(self, env, sent) -> None:
        put_item(env, "MLA1", checked=ago(30))
        notify(env, "MLA1", received=ago(7))

        first = handlers.freshness.run(context())
        handlers.freshness.run(context())

        assert first.success is True
        assert len(sent) == 1
        assert "estado de la publicación" in sent[0]
        assert "1 publicación" in sent[0]

        run(env, "DELETE FROM ml_pub_refresh_queue")
        handlers.freshness.run(context())
        handlers.freshness.run(context())

        assert len(sent) == 2
        assert "al día" in sent[1]

    def test_an_unsent_alert_is_retried_on_the_next_tick(self, env, monkeypatch) -> None:
        put_item(env, "MLA1", checked=ago(30))
        notify(env, "MLA1", received=ago(7))
        outcomes = iter(["not_configured", "sent"])
        tries: List[str] = []

        def send(message: str) -> str:
            tries.append(message)
            return next(outcomes)

        monkeypatch.setattr(handlers.wabot_client, "send_to_owner", send)

        result = handlers.freshness.run(context())
        assert result.detail["alert"] == "not_configured"
        handlers.freshness.run(context())
        handlers.freshness.run(context())

        assert len(tries) == 2

    def test_a_resource_late_again_after_recovering_alerts_again_while_another_stays_late(self, env, sent) -> None:
        put_item(env, "MLA1", checked=ago(30))
        notify(env, "MLA1", received=ago(7), resources=("core",))
        put_item(env, "MLA2", checked=ago(30))
        notify(env, "MLA2", received=ago(10), resources=("promotions",))
        handlers.freshness.run(context())
        assert len(sent) == 1

        run(env, "DELETE FROM ml_pub_refresh_queue WHERE entity_id = 'MLA2'")  # promotions back, status still late
        handlers.freshness.run(context())
        notify(env, "MLA2", received=ago(10), resources=("promotions",))  # promotions late again
        handlers.freshness.run(context())

        assert len(sent) == 2
        assert "promociones" in sent[1]
