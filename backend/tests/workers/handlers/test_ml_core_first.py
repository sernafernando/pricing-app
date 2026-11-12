"""`ml_publications.core_first` (S1c): during a notification burst the item cores of the waiting notification-lane
entries are read from `/items/bulk` ahead of everyone's sub-resources, without claiming or deleting the entries; the
refresh then skips a core that is already newer than the entry's last notification and fetches only the
sub-resources.

Postgres only (queue, row locks). Bulk bodies are the real captures served by `httpx.MockTransport`; the 429 is
synthetic (none was captured).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.ml_publications import freshness, settings_store
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.services.ml_publications.queue import LANE_MANUAL, LANE_NOTIFICATION, LANE_RECONCILE
from app.workers.context import JobResult
from app.workers.handlers import ml_core_first
from tests.workers.handlers.test_ml_publications_bundle_policy import paths, responder_with
from tests.workers.handlers.test_ml_publications_refresh import (
    FakeClock,
    NoCallTransport,
    ScriptedTransport,
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

ITEM = "MLA935110613"


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
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


def make_core_first(transport: httpx.BaseTransport, pacer: Pacer | None = None) -> ml_core_first.CoreFirstHandler:
    def factory(pacer_: Pacer) -> MlHttpClient:
        return MlHttpClient(
            pacer=pacer_, transport=transport, token_loader=lambda: {"access_token": "tok", "expires_epoch": 9e12}
        )

    return ml_core_first.CoreFirstHandler(client_factory=factory, pacer=pacer or Pacer(clock=FakeClock()))


def burst(*ids: str, lane: int = LANE_NOTIFICATION, resources=("bundle",)) -> None:
    enqueue_items(*ids, lane=lane, resources=resources)


def unclaimed(engine) -> int:
    return sql_scalar(engine, "SELECT count(*) FROM ml_pub_refresh_queue WHERE claimed_at IS NULL")


class TestCoreFirst:
    def test_45_waiting_entries_are_read_in_groups_of_20_20_and_5_and_stay_queued_unclaimed(self, env) -> None:
        enable_refresh(bundle_resources=["core", "prices"])
        ids = [f"MLA{n}" for n in range(100, 145)]
        burst(*ids)
        transport = ScriptedTransport(bulk_responder)

        result = make_core_first(transport).run(context())

        assert result.success is True and result.detail["fetched"] == 45
        assert paths(transport) == ["/items/bulk"] * 3  # no sub-resource call
        assert [len(group) for group in transport.ids()] == [20, 20, 5]
        assert sorted(i for group in transport.ids() for i in group) == sorted(ids)
        assert sql_scalar(env, "SELECT count(*) FROM ml_items WHERE fetched_request_started_at IS NOT NULL") == 45
        assert unclaimed(env) == 45
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_refresh_queue WHERE attempts > 0") == 0

    def test_a_tick_reads_at_most_its_group_cap(self, env) -> None:
        enable_refresh()
        burst(*[f"MLA{n}" for n in range(100, 170)])
        transport = ScriptedTransport(bulk_responder)

        make_core_first(transport).run(context())

        assert len(transport.requests) == ml_core_first.MAX_GROUPS_PER_TICK == 3
        assert sum(len(group) for group in transport.ids()) == 60

    def test_fresh_cores_other_lanes_claimed_entries_other_kinds_and_core_less_entries_are_not_read(self, env) -> None:
        enable_refresh()
        burst(ITEM)
        make_core_first(ScriptedTransport(bulk_responder)).run(context())  # ITEM's core is now fresh
        burst("MLA200", lane=LANE_MANUAL)
        burst("MLA201", lane=LANE_RECONCILE)
        burst("MLA202")
        burst("MLA203", resources=("promotions",))
        enqueue_items_of_kind("user_product", "MLAU1")
        with env.begin() as conn:
            conn.execute(text("UPDATE ml_pub_refresh_queue SET claimed_at = now() WHERE entity_id = 'MLA202'"))
        transport = NoCallTransport()

        result = make_core_first(transport).run(context())

        assert transport.requests == []
        assert result.detail["fetched"] == 0

    def test_a_notification_newer_than_the_stored_core_is_read_again(self, env) -> None:
        enable_refresh()
        burst(ITEM)
        make_core_first(ScriptedTransport(bulk_responder)).run(context())
        burst(ITEM)  # a new notification after the core was read
        transport = ScriptedTransport(bulk_responder)

        make_core_first(transport).run(context())

        assert transport.ids() == [[ITEM]]

    def test_the_flag_off_makes_no_call(self, env) -> None:
        enable_refresh(core_first__enabled=False)
        burst(ITEM)
        transport = NoCallTransport()

        result = make_core_first(transport).run(context())

        assert result == JobResult(success=False, detail={"disabled": True})
        assert transport.requests == []

    def test_the_refresh_flag_off_makes_no_call_either(self, env) -> None:
        burst(ITEM)  # refresh.enabled defaults off: a fresh deploy stays inert
        transport = NoCallTransport()

        assert make_core_first(transport).run(context()) == JobResult(success=False, detail={"disabled": True})

    def test_a_429_stops_the_tick_and_the_next_tick_respects_the_cooldown(self, env) -> None:
        """Synthetic fault: ML answers 429 with Retry-After 30."""
        enable_refresh()
        burst(*[f"MLA{n}" for n in range(100, 145)])
        pacer = Pacer(clock=FakeClock())
        limited = ScriptedTransport(lambda request, call: json_response({}, status=429, headers={"Retry-After": "30"}))

        result = make_core_first(limited, pacer).run(context())

        assert len(limited.requests) == 1
        assert result.success is True and result.detail["stopped"] == "rate_limited"
        assert sql_scalar(env, "SELECT count(*) FROM ml_items") == 0
        assert unclaimed(env) == 45
        assert pacer.cooldown_remaining("items_bulk") > 0
        again = NoCallTransport()
        assert make_core_first(again, pacer).run(context()).detail["stopped"] == "rate_limited"
        assert again.requests == []

    def test_an_item_whose_core_cannot_be_applied_is_not_retried_every_tick(self, env) -> None:
        """Synthetic fault: the bulk element answers 500, so the stored core stays older than the notification."""
        enable_refresh()
        burst(ITEM)
        failing = ScriptedTransport(lambda r, c: json_response([{"id": ITEM, "code": 500, "body": {}}]))
        handler = make_core_first(failing)

        handler.run(context())
        handler.run(context())

        assert len(failing.requests) == 1  # the refresh retries it; core-first does not loop on it


def enqueue_items_of_kind(kind: str, entity_id: str) -> None:
    from app.services.ml_publications.queue import EnqueueEntry, enqueue

    enqueue([EnqueueEntry(kind=kind, entity_id=entity_id, lane=LANE_NOTIFICATION, resources=("bundle",))])


class TestFreshness:
    def test_the_items_lateness_of_a_burst_entry_clears_while_its_entry_waits_for_its_sub_resources(self, env) -> None:
        enable_refresh(bundle_resources=["core", "prices"])
        with env.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_pub_refresh_queue (kind, entity_id, resources, lane, source_received_at) "
                    "VALUES ('item', :i, '{bundle}', 1, :at)"
                ),
                {"i": ITEM, "at": datetime.now(timezone.utc) - timedelta(minutes=6)},
            )

        def measured() -> dict:
            with env.connect() as conn:
                return freshness.measure(Session(bind=conn))["resources"]

        assert measured()["items"]["late"] == 1

        make_core_first(ScriptedTransport(bulk_responder)).run(context())

        assert measured()["items"]["late"] == 0
        assert queue_row(env, ITEM)["resources"] == ["bundle"]  # prices still to fetch by the refresh
        assert measured()["prices"]["late"] == 1  # the refresh still owes it


class TestTheRefreshAfterCoreFirst:
    def test_the_refresh_skips_a_fresh_core_and_still_fetches_the_sub_resources(self, env) -> None:
        enable_refresh(bundle_resources=["core", "prices"])
        burst(ITEM)
        make_core_first(ScriptedTransport(bulk_responder)).run(context())
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport) == [f"/items/{ITEM}/prices"]  # no /items/bulk for this entry
        assert sql_scalar(env, "SELECT count(*) FROM ml_item_prices WHERE item_id = :i", i=ITEM) == 1
        assert queue_row(env, ITEM) is None  # settled

    def test_the_refresh_reads_the_core_when_a_notification_is_newer_than_it(self, env) -> None:
        enable_refresh(bundle_resources=["core", "prices"])
        burst(ITEM)
        make_core_first(ScriptedTransport(bulk_responder)).run(context())
        burst(ITEM)  # newer notification: the stored core no longer covers it
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk", f"/items/{ITEM}/prices"]
        assert queue_row(env, ITEM) is None

    def test_a_manual_entry_always_reads_its_core(self, env) -> None:
        enable_refresh()
        burst(ITEM)
        make_core_first(ScriptedTransport(bulk_responder)).run(context())
        enqueue_items(ITEM, lane=LANE_MANUAL)  # the entry moves to lane 0: an explicit request
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]

    def test_with_the_flag_off_the_refresh_reads_every_core_as_before(self, env) -> None:
        enable_refresh()
        burst(ITEM)
        make_core_first(ScriptedTransport(bulk_responder)).run(context())
        settings_store.set_setting("core_first.enabled", False, "test")
        transport = ScriptedTransport(responder_with())

        make_handler(transport).run(context())

        assert paths(transport) == ["/items/bulk"]
        assert queue_row(env, ITEM) is None

    def test_a_skipped_core_of_a_gone_item_settles_without_sub_resources(self, env) -> None:
        enable_refresh(bundle_resources=["core", "prices"])
        burst("MLA1")  # the real not-found element
        make_core_first(ScriptedTransport(bulk_responder)).run(context())
        transport = NoCallTransport()

        make_handler(transport).run(context())

        assert transport.requests == []
        assert queue_row(env, "MLA1") is None
