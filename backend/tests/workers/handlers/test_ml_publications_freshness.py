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

    # Owner, 2026-11-03: "pero 5 segundos de diferencia no es demora si el objetivo es dos min, tendríamos que
    # tener un 5% de tolerancia".
    def test_a_delay_within_five_percent_of_the_target_is_not_late(self, env) -> None:
        put_item(env, "MLA1", checked=ago(30))
        notify(env, "MLA1", received=datetime.now(timezone.utc) - timedelta(seconds=125))  # target 120, +4 %
        put_item(env, "MLA2", checked=ago(30))
        notify(env, "MLA2", received=datetime.now(timezone.utc) - timedelta(seconds=130))  # +8 %

        items = measure(env)["resources"]["items"]

        assert items["late"] == 1
        assert 129 < items["oldest_late_seconds"] < 140

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


class TestFamilies:
    """The queue keys a family entry by its id as text while `ml_items.family_id` is a bigint (prod error
    "los tipos bigint y text no son coincidentes en CASE", 2026-11-03): the family measure must run on Postgres."""

    def _put_family_item(self, engine, item_id: str, family_id: int) -> None:
        put_item(engine, item_id, checked=ago(1))
        run(engine, "UPDATE ml_items SET family_id = :f WHERE item_id = :i", f=family_id, i=item_id)

    def test_a_family_waiting_past_its_target_is_late_once_however_it_was_asked(self, env) -> None:
        settings_store.set_setting("bundle_resources", ["core", "family"], "test")
        self._put_family_item(env, "MLA1", 5001)
        self._put_family_item(env, "MLA2", 5001)
        run(
            env,
            "INSERT INTO ml_user_product_families (family_id, http_status, last_checked_at) VALUES (5001, 200, :c)",
            c=ago(60 * 72),
        )
        two_days = ago(60 * 48)
        notify(env, "MLA1", received=two_days)
        notify(env, "MLA2", received=two_days)
        run(
            env,
            "INSERT INTO ml_pub_refresh_queue (kind, entity_id, resources, lane, source_received_at) "
            "VALUES ('family', '5001', '{family}', 1, :at)",
            at=two_days,
        )

        family = measure(env)["resources"]["family"]

        assert family["target_seconds"] == 86400
        assert family["late"] == 1
        assert 48 * 3600 - 60 < family["oldest_late_seconds"] < 48 * 3600 + 60

    def test_a_family_checked_since_the_notification_is_not_late(self, env) -> None:
        settings_store.set_setting("bundle_resources", ["core", "family"], "test")
        self._put_family_item(env, "MLA1", 5001)
        run(
            env,
            "INSERT INTO ml_user_product_families (family_id, http_status, last_checked_at) VALUES (5001, 200, :c)",
            c=ago(1),
        )
        notify(env, "MLA1", received=ago(60 * 48))

        assert measure(env)["resources"]["family"]["late"] == 0


class TestVisits:
    def test_measured_only_while_the_sweep_collects_them(self, env) -> None:
        put_item(env, "MLA1", checked=ago(1))
        put_checked(env, "ml_item_visits", "MLA1", ago(60 * 30))
        settings_store.set_setting("bundle_resources", ["core", "visits"], "test")
        assert "visits" not in measure(env)["resources"]

        settings_store.set_setting("sweep.enabled", True, "test")
        visits = measure(env)["resources"]["visits"]
        assert visits["late"] == 1


def put_sweep_tick(engine, scope: str, *, started: datetime, outcome: str = "success") -> None:
    run(
        engine,
        "INSERT INTO ml_pub_job_runs (job, scope, started_at, finished_at, outcome, counts) "
        "VALUES ('sweep', :scope, :started, :started, :outcome, '{}')",
        scope=scope,
        started=started,
        outcome=outcome,
    )


class TestDescription:
    """2026-11-12: swept once a day, so measured like visits: the age of the last check on active items. Until the
    sweep has had a full target since its first tick that sweeps the description, nothing is late (no false
    alert the day it starts)."""

    def enable(self) -> None:
        settings_store.set_setting("bundle_resources", ["core", "description"], "test")
        settings_store.set_setting("sweep.enabled", True, "test")

    def test_a_description_unchecked_for_more_than_a_day_is_late_once_the_sweep_had_a_full_lap(self, env) -> None:
        put_item(env, "MLA1", checked=ago(1))
        put_checked(env, "ml_item_descriptions", "MLA1", ago(60 * 30))
        put_item(env, "MLA2", checked=ago(1))
        put_checked(env, "ml_item_descriptions", "MLA2", ago(60 * 23))
        put_sweep_tick(env, "description,visits", started=ago(60 * 48))
        settings_store.set_setting("bundle_resources", ["core", "description"], "test")
        assert "description" not in measure(env)["resources"]

        settings_store.set_setting("sweep.enabled", True, "test")
        description = measure(env)["resources"]["description"]
        assert (description["late"], description["target_seconds"]) == (1, 86400)

    def test_nothing_is_late_before_the_first_sweep_tick_of_the_description(self, env) -> None:
        put_item(env, "MLA1", checked=ago(1))
        put_checked(env, "ml_item_descriptions", "MLA1", ago(60 * 30))
        put_sweep_tick(env, "visits", started=ago(60 * 48))
        put_sweep_tick(env, "description,visits", started=ago(5), outcome="failed")
        self.enable()
        assert measure(env)["resources"]["description"]["late"] == 0

    def test_the_first_lap_has_the_target_as_grace_from_the_first_tick(self, env) -> None:
        put_item(env, "MLA1", checked=ago(1))
        put_checked(env, "ml_item_descriptions", "MLA1", ago(60 * 30))
        put_sweep_tick(env, "description,visits", started=ago(60 * 20))
        self.enable()
        assert measure(env)["resources"]["description"]["late"] == 0

        put_sweep_tick(env, "description,visits", started=ago(60 * 27))
        late = measure(env)["resources"]["description"]
        assert late["late"] == 1 and 60 * 60 * 26.5 < late["oldest_late_seconds"] < 60 * 60 * 27.5

    def test_visits_are_measured_as_before_without_a_grace(self, env) -> None:
        put_item(env, "MLA1", checked=ago(1))
        put_checked(env, "ml_item_visits", "MLA1", ago(60 * 30))
        settings_store.set_setting("bundle_resources", ["core", "visits"], "test")
        settings_store.set_setting("sweep.enabled", True, "test")
        assert measure(env)["resources"]["visits"]["late"] == 1

    def test_a_bundle_notification_does_not_make_the_description_late(self, env) -> None:
        put_item(env, "MLA1", checked=ago(1))
        put_checked(env, "ml_item_descriptions", "MLA1", ago(60 * 2))
        put_sweep_tick(env, "description", started=ago(60 * 48))
        notify(env, "MLA1", received=ago(60 * 3))
        self.enable()
        assert measure(env)["resources"]["description"]["late"] == 0


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

    def test_it_alerts_once_while_late_and_once_when_back_for_the_quiet_hour(self, env, sent, monkeypatch) -> None:
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
        assert len(sent) == 1  # back for a moment only: no "al día" yet

        later = datetime.now(timezone.utc) + handlers.FRESHNESS_QUIET + timedelta(minutes=1)
        monkeypatch.setattr(handlers, "_utcnow", lambda: later)
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

    # Owner, 2026-11-03: "esto me está plagueando, que no me avise por los mismos estados cada 5 min". Resources
    # hovering around their target went late, back and late again every few minutes, and each return re-alerted.

    def test_a_resource_late_again_soon_after_recovering_does_not_alert_again(self, env, sent) -> None:
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

        assert len(sent) == 1

    def test_everything_back_for_a_moment_neither_says_back_nor_alerts_again(self, env, sent) -> None:
        put_item(env, "MLA1", checked=ago(30))
        notify(env, "MLA1", received=ago(7))
        handlers.freshness.run(context())

        run(env, "DELETE FROM ml_pub_refresh_queue")
        handlers.freshness.run(context())
        notify(env, "MLA1", received=ago(7))
        handlers.freshness.run(context())

        assert len(sent) == 1

    def test_a_resource_late_again_after_the_quiet_hour_alerts_again(self, env, sent, monkeypatch) -> None:
        put_item(env, "MLA1", checked=ago(30))
        notify(env, "MLA1", received=ago(7), resources=("core",))
        put_item(env, "MLA2", checked=ago(30))
        notify(env, "MLA2", received=ago(10), resources=("promotions",))
        handlers.freshness.run(context())

        run(env, "DELETE FROM ml_pub_refresh_queue WHERE entity_id = 'MLA2'")
        handlers.freshness.run(context())
        later = datetime.now(timezone.utc) + handlers.FRESHNESS_QUIET + timedelta(minutes=1)
        monkeypatch.setattr(handlers, "_utcnow", lambda: later)
        handlers.freshness.run(context())  # promotions on time for longer than the quiet hour: forgotten
        notify(env, "MLA2", received=ago(10), resources=("promotions",))
        handlers.freshness.run(context())

        assert len(sent) == 2
        assert "promociones" in sent[1]
