"""`ml_publications.relink` (design D20): the re-link sweep of the product links.

Postgres only. Items are real captures written through `apply_fetch` with `links.enabled` OFF
(so the sweep is what links them); `productos_erp` rows are plain test data. The sweep makes no ML
call: any client request fails the test.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import event, text

from app.core import database
from app.core.config import settings
from app.models.producto import ProductoERP
from app.services.ml_publications import links, settings_store
from app.services.ml_publications.ml_http import MlHttpClient
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers import ml_publications as handlers
from app.workers.runtime import WorkerRuntime
from tests.services.ml_publications.conftest import bulk_item, sample_item
from tests.services.ml_publications.test_links_store import (
    SKU_A,
    SKU_B,
    add_product,
    link,
    link_rows,
    log_rows,
    put_link,
)
from tests.services.ml_publications.test_store_apply_fetch import apply

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 10, 6, 15, 0, 0, tzinfo=timezone.utc)  # 12:00 in Argentina: past the 04:30 slot
ITEMS = ["MLA874027718", "MLA882393030"]  # two real items sharing SELLER_SKU SKU_A
THIRD = "MLA935110613"  # real item with SELLER_SKU SKU_B


def context(seconds: float = 60.0) -> WorkerContext:
    return WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=seconds), worker_name="worker-ml")


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
    ProductoERP.__table__.create(bind=mlpub_pg)
    with mlpub_pg.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE worker_job_state (name varchar(64) PRIMARY KEY, last_run_at timestamptz, "
                "last_success_at timestamptz, state varchar(32), detail jsonb, heartbeat_at timestamptz)"
            )
        )
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)

    def no_ml_call(*args, **kwargs):
        pytest.fail("the re-link sweep must not call ML")

    monkeypatch.setattr(MlHttpClient, "get", no_ml_call)
    return mlpub_pg


def seed_items(*ids: str) -> None:
    """Store real items with links OFF, so nothing is linked yet."""
    for minutes, item_id in enumerate(ids, start=1):
        body = sample_item(item_id) if item_id in ITEMS else bulk_item(item_id)
        apply(body, item_id, minutes=minutes, links_enabled=False, events_enabled=False)


def enable(*flags: str) -> None:
    for flag in flags:
        settings_store.set_setting(f"{flag}.enabled", True, "test")


def run(**kwargs) -> JobResult:
    return handlers.RelinkHandler().run(context(**kwargs))


def state(engine, key: str):
    with engine.connect() as conn:
        return conn.execute(text("SELECT value FROM ml_pub_settings WHERE key = :k"), {"k": key}).scalar()


class TestDisabledOutcome:
    def test_flag_off_reads_and_writes_nothing_and_keeps_the_slot(self, env) -> None:
        seed_items(*ITEMS)
        statements: list[str] = []

        def record(conn, cursor, statement, *rest):
            statements.append(statement)

        event.listen(env, "before_cursor_execute", record)
        try:
            result = run()
        finally:
            event.remove(env, "before_cursor_execute", record)

        assert result == JobResult(success=False, detail={"disabled": True})
        assert not [s for s in statements if "productos_erp" in s or "ml_items" in s or "ml_item_product_links" in s]
        assert link_rows(env) == []
        assert state(env, "links.sweep_state") is None

    def test_the_runtime_does_not_consume_the_slot_of_a_disabled_handler(self, env) -> None:
        handler = handlers.RelinkHandler()
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        now = datetime.now(timezone.utc)

        assert runtime._run_handler(handler, now) is False

        assert runtime._due_handlers(now) == [handler]

    def test_kill_switch_overrides_a_db_enabled_flag(self, env, monkeypatch) -> None:
        enable("links")
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)
        assert run() == JobResult(success=False, detail={"disabled": True})


class TestSchedule:
    def test_it_is_a_fifteen_minute_interval_job_that_is_not_notify_driven(self) -> None:
        handler = handlers.relink
        assert handler.name == "ml_publications.relink"
        assert handler.interval == timedelta(minutes=15)
        assert handler.run_at_local is None
        assert handler.channels == ()


class TestFirstPass:
    def test_never_evaluated_units_are_evaluated_and_linked_without_an_ml_call(self, env) -> None:
        seed_items(*ITEMS, THIRD)
        add_product(env, 41, SKU_A)
        add_product(env, 42, SKU_B)
        enable("links")

        result = run()

        assert result.success is True
        assert result.detail["complete"] is True
        assert result.detail["created"] == 3
        assert [(r["item_id"], r["producto_item_id"]) for r in link_rows(env)] == [
            ("MLA874027718", 41),
            ("MLA882393030", 41),
            (THIRD, 42),
        ]
        assert log_rows(env) == []  # first sighting writes no history

    def test_items_are_read_in_keyset_batches(self, env, monkeypatch) -> None:
        monkeypatch.setattr(links, "SWEEP_BATCH", 2)
        seed_items(*ITEMS, THIRD)
        add_product(env, 41, SKU_A)
        enable("links")

        result = run()

        assert result.detail["batches"] == 2
        assert len(link_rows(env)) == 3

    def test_the_catalog_fingerprint_is_stored_when_the_lap_completes(self, env) -> None:
        seed_items(*ITEMS)
        enable("links")
        run()
        assert isinstance(state(env, "links.catalog_fingerprint"), str)
        assert state(env, "links.sweep_state") == {
            "cursor": None,
            "force": False,
            "target": None,
            "retry": False,
        }


class TestIncrementalPasses:
    def test_nothing_changed_means_nothing_evaluated_and_no_full_pass(self, env, monkeypatch) -> None:
        seed_items(*ITEMS)
        add_product(env, 41, SKU_A)
        enable("links")
        run()
        calls: list[bool] = []
        original = links.evaluate_item

        def spy(*args, **kwargs):
            calls.append(kwargs.get("force"))
            return original(*args, **kwargs)

        monkeypatch.setattr(links, "evaluate_item", spy)

        result = run()

        assert calls == []
        assert result.detail["skipped"] == 2 and result.detail["created"] == 0

    def test_a_unit_whose_sku_key_changed_since_its_evaluation_is_reevaluated(self, env) -> None:
        seed_items(*ITEMS)
        add_product(env, 41, SKU_A)
        add_product(env, 42, SKU_B)
        enable("links", "events")
        run()
        changed = sample_item("MLA882393030")
        changed["attributes"] = [
            {**a, "value_name": SKU_B} if a["id"] == "SELLER_SKU" else a for a in changed["attributes"]
        ]  # real payload, one value changed
        apply(changed, "MLA882393030", minutes=30, links_enabled=False, events_enabled=False)

        result = run()

        assert result.detail["changed"] == 1
        assert link(env, "MLA882393030")["producto_item_id"] == 42
        assert link(env, "MLA874027718")["producto_item_id"] == 41
        (entry,) = log_rows(env)
        assert entry["entity_id"] == "MLA882393030:0"


class TestCatalogChange:
    def test_a_new_product_links_an_unmatched_unit_with_no_ml_call(self, env) -> None:
        seed_items(*ITEMS)
        enable("links", "events")
        run()
        assert link(env, "MLA882393030")["match_status"] == "unmatched"
        add_product(env, 41, SKU_A)

        result = run()

        assert result.detail["changed"] == 2
        assert link(env, "MLA882393030")["producto_item_id"] == 41
        assert len(log_rows(env)) == 2

    def test_the_catalog_fingerprint_changes_with_a_codigo_edit_not_only_with_new_rows(self, env) -> None:
        seed_items(*ITEMS)
        add_product(env, 41, "OLD")
        enable("links")
        run()
        first = state(env, "links.catalog_fingerprint")
        with env.begin() as conn:
            conn.execute(text("UPDATE productos_erp SET codigo = :c WHERE item_id = 41"), {"c": SKU_A})

        run()

        assert state(env, "links.catalog_fingerprint") != first
        assert link(env, "MLA882393030")["producto_item_id"] == 41

    def test_a_forced_lap_refreshes_the_suggestion_of_a_manual_unit_and_never_moves_it(self, env) -> None:
        seed_items(*ITEMS)
        put_link(env, "MLA882393030", 0, "manual", "linked", 7, linked_by=3)
        add_product(env, 41, SKU_A)
        enable("links")

        result = run()

        row = link(env, "MLA882393030")
        assert (row["source"], row["producto_item_id"], row["linked_by"]) == ("manual", 7, 3)
        assert row["suggested_producto_item_id"] == 41
        assert result.detail["manual_differs"] == 1
        assert log_rows(env) == []


class TestDailyFullPass:
    def _calls_forced(self, monkeypatch) -> list:
        calls: list = []
        original = links.evaluate_item

        def spy(*args, **kwargs):
            calls.append(kwargs.get("force"))
            return original(*args, **kwargs)

        monkeypatch.setattr(links, "evaluate_item", spy)
        return calls

    def test_a_pass_after_the_slot_with_no_pass_since_yesterday_is_a_full_pass(self, env, monkeypatch) -> None:
        seed_items(*ITEMS)
        add_product(env, 41, SKU_A)
        enable("links")
        links.run_sweep(deadline=NOW + timedelta(minutes=5), gate=lambda: False, now=lambda: NOW - timedelta(days=2))
        calls = self._calls_forced(monkeypatch)

        links.run_sweep(deadline=NOW + timedelta(minutes=5), gate=lambda: False, now=lambda: NOW)

        assert calls == [True, True]

    def test_after_a_full_pass_today_the_next_pass_is_incremental(self, env, monkeypatch) -> None:
        seed_items(*ITEMS)
        add_product(env, 41, SKU_A)
        enable("links")
        links.run_sweep(deadline=NOW + timedelta(minutes=5), gate=lambda: False, now=lambda: NOW)
        calls = self._calls_forced(monkeypatch)

        links.run_sweep(
            deadline=NOW + timedelta(minutes=5), gate=lambda: False, now=lambda: NOW + timedelta(minutes=20)
        )

        assert calls == []

    def test_before_the_slot_there_is_no_daily_pass(self, env, monkeypatch) -> None:
        seed_items(*ITEMS)
        add_product(env, 41, SKU_A)
        enable("links")
        links.run_sweep(deadline=NOW + timedelta(minutes=5), gate=lambda: False, now=lambda: NOW - timedelta(days=2))
        calls = self._calls_forced(monkeypatch)
        before_slot = datetime(2026, 10, 6, 6, 0, 0, tzinfo=timezone.utc)  # 03:00 in Argentina

        links.run_sweep(deadline=before_slot + timedelta(minutes=5), gate=lambda: False, now=lambda: before_slot)

        assert calls == []

    def test_a_forced_lap_that_finishes_after_the_slot_counts_as_todays_full_pass(self, env, monkeypatch) -> None:
        seed_items(*ITEMS)
        add_product(env, 41, SKU_A)
        enable("links")
        before_slot = datetime(2026, 10, 6, 7, 20, 0, tzinfo=timezone.utc)  # 04:20 in Argentina
        after_slot = datetime(2026, 10, 6, 7, 50, 0, tzinfo=timezone.utc)  # 04:50 in Argentina
        clock = iter([before_slot, before_slot, after_slot, after_slot])
        links.run_sweep(
            deadline=after_slot + timedelta(hours=1), gate=lambda: False, now=lambda: next(clock, after_slot)
        )
        calls = self._calls_forced(monkeypatch)

        later = after_slot + timedelta(minutes=20)
        links.run_sweep(deadline=later + timedelta(minutes=5), gate=lambda: False, now=lambda: later)

        assert calls == []

    def test_the_daily_slot_is_04_30_argentina_time(self) -> None:
        assert links.DAILY_PASS_AT == time(4, 30)


class TestDeadlineAndResume:
    def test_it_stops_at_the_deadline_and_resumes_from_its_keyset_cursor(self, env, monkeypatch) -> None:
        monkeypatch.setattr(links, "SWEEP_BATCH", 1)
        seed_items(*ITEMS, THIRD)
        add_product(env, 41, SKU_A)
        enable("links")
        ticks = iter([NOW, NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=1)])
        deadline = NOW + timedelta(minutes=5)

        first = links.run_sweep(
            deadline=deadline, gate=lambda: False, now=lambda: next(ticks, NOW + timedelta(hours=1))
        )

        assert first.complete is False and first.stopped == "deadline"
        done = [r["item_id"] for r in link_rows(env)]
        assert done == ["MLA874027718"]
        assert state(env, "links.sweep_state")["cursor"] == "MLA874027718"
        seen: list[str] = []
        original = links.evaluate_item

        def spy(db, item_id, *args, **kwargs):
            seen.append(item_id)
            return original(db, item_id, *args, **kwargs)

        monkeypatch.setattr(links, "evaluate_item", spy)

        second = links.run_sweep(deadline=NOW + timedelta(minutes=30), gate=lambda: False, now=lambda: NOW)

        assert second.complete is True
        assert seen == ["MLA882393030", THIRD]
        assert len(link_rows(env)) == 3

    def test_the_deadline_is_also_checked_inside_a_batch(self, env) -> None:
        seed_items(*ITEMS, THIRD)
        add_product(env, 41, SKU_A)
        enable("links")
        ticks = iter([NOW, NOW, NOW + timedelta(hours=1)])  # start, batch top, after the first item

        result = links.run_sweep(
            deadline=NOW + timedelta(minutes=5), gate=lambda: False, now=lambda: next(ticks, NOW + timedelta(hours=1))
        )

        assert result.stopped == "deadline" and result.complete is False
        assert [r["item_id"] for r in link_rows(env)] == ["MLA874027718"]
        assert state(env, "links.sweep_state")["cursor"] == "MLA874027718"

    def test_the_flag_turned_off_between_batches_stops_the_run(self, env, monkeypatch) -> None:
        monkeypatch.setattr(links, "SWEEP_BATCH", 1)
        seed_items(*ITEMS)
        enable("links")
        answers = iter([False, None])

        result = links.run_sweep(deadline=NOW + timedelta(minutes=5), gate=lambda: next(answers), now=lambda: NOW)

        assert result.stopped == "disabled" and result.complete is False
        assert len(link_rows(env)) == 1

    def test_one_failing_item_is_counted_and_does_not_stop_the_lap(self, env, monkeypatch) -> None:
        seed_items(*ITEMS)
        enable("links")
        original = links.evaluate_item

        def flaky(db, item_id, *args, **kwargs):
            if item_id == "MLA874027718":
                raise RuntimeError("catalog hiccup")
            return original(db, item_id, *args, **kwargs)

        monkeypatch.setattr(links, "evaluate_item", flaky)

        result = run()

        assert result.detail["errors"] == 1 and result.detail["complete"] is True
        assert result.detail["retry"] is True  # visible in the job detail: the forced lap will be redone
        assert [r["item_id"] for r in link_rows(env)] == ["MLA882393030"]


def _with_sku(sku: str) -> dict:
    """Real MLA882393030 with its SELLER_SKU value changed (one field)."""
    body = sample_item("MLA882393030")
    body["attributes"] = [{**a, "value_name": sku} if a["id"] == "SELLER_SKU" else a for a in body["attributes"]]
    return body


class TestConcurrencyWithApplyFetch:
    def test_a_fetch_that_commits_between_the_snapshot_and_the_evaluation_is_not_reverted(
        self, env, monkeypatch
    ) -> None:
        """The sweep read the item's SKU, then a refresh committed a new SKU and its link; the sweep must
        evaluate the CURRENT SKU, never write the previous product back (and log a change that never happened)."""
        add_product(env, 41, SKU_A)
        add_product(env, 42, SKU_B)
        enable("links", "events")
        apply(sample_item("MLA882393030"), "MLA882393030", minutes=1)  # linked to 41 by the hook
        add_product(env, 43, "NEW")  # catalog changed: the next lap is forced
        original = links._typed_batch
        raced: list[bool] = []

        def snapshot_then_refresh(db, cursor, size):
            batch = original(db, cursor, size)
            if not raced:
                raced.append(True)
                apply(_with_sku(SKU_B), "MLA882393030", minutes=30, links_enabled=True, events_enabled=True)
            return batch

        monkeypatch.setattr(links, "_typed_batch", snapshot_then_refresh)

        result = run()

        assert result.detail["complete"] is True
        assert link(env, "MLA882393030")["producto_item_id"] == 42
        (entry,) = log_rows(env)  # exactly the refresh's own change, no second one from the sweep
        assert (entry["context"]["producto_item_id_old"], entry["context"]["producto_item_id_new"]) == (41, 42)

    def test_the_link_locks_of_an_item_are_released_before_the_next_item_starts(self, env, monkeypatch) -> None:
        seed_items(*ITEMS)
        add_product(env, 41, SKU_A)
        enable("links")
        run()  # both units exist now, so the forced lap below locks real rows
        add_product(env, 43, "NEW")  # catalog changed: the next lap is forced
        original = links.evaluate_item
        free: list[bool] = []

        def spy(db, item_id, *args, **kwargs):
            if item_id == "MLA882393030":  # the second item: the first one's rows must be free by now
                try:
                    with env.begin() as conn:
                        conn.execute(text("SET LOCAL lock_timeout = '200ms'"))
                        conn.execute(
                            text("SELECT 1 FROM ml_item_product_links WHERE item_id = 'MLA874027718' FOR UPDATE")
                        )
                    free.append(True)
                except Exception:  # noqa: BLE001
                    free.append(False)
            return original(db, item_id, *args, **kwargs)

        monkeypatch.setattr(links, "evaluate_item", spy)

        run()

        assert free == [True]

    def test_an_item_locked_by_a_fetch_in_flight_is_skipped_not_waited_for_and_the_lap_is_redone(self, env) -> None:
        seed_items(*ITEMS)
        add_product(env, 41, SKU_A)
        enable("links")
        holder = env.connect()
        transaction = holder.begin()
        holder.execute(text("SELECT 1 FROM ml_items WHERE item_id = 'MLA874027718' FOR UPDATE"))
        try:
            result = run()
        finally:
            transaction.rollback()
            holder.close()

        assert result.detail["contended"] == 1 and result.detail["complete"] is True
        assert [r["item_id"] for r in link_rows(env)] == ["MLA882393030"]
        assert state(env, "links.catalog_fingerprint") is None  # the forced lap must be redone
        again = run()
        assert again.detail["contended"] == 0
        assert [r["item_id"] for r in link_rows(env)] == ["MLA874027718", "MLA882393030"]
        assert isinstance(state(env, "links.catalog_fingerprint"), str)


class TestStoredState:
    def test_a_stored_state_missing_its_flags_reads_them_as_false(self, env) -> None:
        with env.begin() as conn:
            conn.execute(
                text("INSERT INTO ml_pub_settings (key, value) VALUES ('links.sweep_state', '{\"cursor\": \"MLA1\"}')")
            )
        with database.get_background_db() as db:
            loaded = links._load_state(db)
        assert (loaded.cursor, loaded.force, loaded.retry) == ("MLA1", False, False)


class TestRegistry:
    def test_the_relink_handler_is_registered_after_refresh_and_intake(self) -> None:
        from app.workers import registry

        assert [h.name for h in registry.ML_PUBLICATIONS_REGISTRY if h.name.startswith("ml_publications.")] == [
            "ml_publications.refresh",
            "ml_publications.intake",
            "ml_publications.relink",
            "ml_publications.scan",
            "ml_publications.missed_feeds",
            "ml_publications.sweep",
            "ml_publications.verify",
        ]
