"""Sweeps of the topic-less resources (design D17): performance and visits, lowest lane, no ML call of their own.

The sweep only SELECTS and ENQUEUES (lane 4, resources named `performance` / `visits`); the refresh handler
fetches under the shared pacing budget. Items are plain rows; the one captured fact the rules rest on, that a
catalog product item answers performance `not_applicable`, is a stored `applicable = false` state.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import queue, sweeps

pytestmark = pytest.mark.postgres

BOTH = ["core", "performance", "visits"]
ACTIVE_ONLY = ["active"]
EVERY_NON_CLOSED = ["active", "paused", "under_review", "inactive", "pending"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    return mlpub_pg


def run(*, statuses=None, bundle=None, recheck_days=30, now=utcnow):
    return sweeps.run_sweep(
        statuses=statuses or EVERY_NON_CLOSED,
        bundle_resources=BOTH if bundle is None else bundle,
        recheck_days=recheck_days,
        now=now,
    )


def put_items(engine, count: int, *, status="active", prefix="MLA1", gone=False, never_existed=False) -> List[str]:
    ids = [f"{prefix}{n:06d}" for n in range(count)]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_items (item_id, status, gone_at, never_existed, http_status, last_checked_at) "
                "VALUES (:id, :status, :gone, :never, 200, now())"
            ),
            [{"id": i, "status": status, "gone": utcnow() if gone else None, "never": never_existed} for i in ids],
        )
    return ids


def put_state(engine, table: str, item_id: str, *, checked_ago_days: Optional[float], applicable=None) -> None:
    columns = "item_id, last_checked_at, http_status" + (", applicable" if table == "ml_item_performance" else "")
    values = ":id, :checked, 200" + (", :applicable" if table == "ml_item_performance" else "")
    params = {
        "id": item_id,
        "checked": None if checked_ago_days is None else utcnow() - timedelta(days=checked_ago_days),
        "applicable": applicable,
    }
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({values})"), params)


def queue_rows(engine) -> Dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT entity_id, lane, resources FROM ml_pub_refresh_queue")).fetchall()
    return {r[0]: {"lane": r[1], "resources": list(r[2])} for r in rows}


def queue_put(engine, entity_id: str, lane: int, *, not_before_hours: float = 0, resources="{bundle}") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_pub_refresh_queue (kind, entity_id, resources, lane, not_before) "
                "VALUES ('item', :id, CAST(:r AS text[]), :lane, now() + (:h * interval '1 hour'))"
            ),
            {"id": entity_id, "r": resources, "lane": lane, "h": not_before_hours},
        )


def run_records(engine) -> List[dict]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(text("SELECT * FROM ml_pub_job_runs WHERE job = 'sweep' ORDER BY id")).mappings()
        ]


class TestBatchSize:
    """K = ceil(eligible / 144): a tick every 10 minutes is 144 a day, so the oldest K per tick cover every
    eligible item once a day."""

    @pytest.mark.parametrize(
        "eligible, expected", [(0, 0), (1, 1), (144, 1), (145, 2), (288, 2), (289, 3), (24_600, 171)]
    )
    def test_it_is_the_ceiling_of_eligible_over_the_ticks_of_a_day(self, eligible, expected) -> None:
        assert sweeps.batch_size(eligible) == expected == math.ceil(eligible / 144)

    def test_a_day_of_ticks_covers_every_eligible_item(self) -> None:
        for eligible in (1, 143, 144, 145, 1000, 24_600):
            assert sweeps.batch_size(eligible) * sweeps.TICKS_PER_DAY >= eligible

    def test_the_documented_sizing_of_the_default_and_the_narrowed_sweep(self) -> None:
        # 24.6k eligible items x 2 resources = about 49k calls a day = 0.57 req/s; ["active"] (about 7.8k
        # items) x 2 = about 15.6k calls a day = 0.18 req/s. The ceiling of K rounds the real figure up a little.
        default = sweeps.daily_calls(24_600, 24_600)
        assert default == 2 * 171 * 144 == 49_248
        assert round(sweeps.requests_per_second(default), 2) == 0.57
        narrowed = sweeps.daily_calls(7_800, 7_800)
        assert narrowed == 2 * 55 * 144 == 15_840
        assert round(sweeps.requests_per_second(narrowed), 2) == 0.18


class TestSelection:
    def test_the_oldest_items_of_each_resource_are_enqueued_in_the_sweep_lane_never_checked_first(self, env) -> None:
        ids = put_items(env, 150)  # K = ceil(150 / 144) = 2
        put_state(env, "ml_item_performance", ids[0], checked_ago_days=0.1)
        put_state(env, "ml_item_performance", ids[1], checked_ago_days=9)
        put_state(env, "ml_item_visits", ids[2], checked_ago_days=0.1)
        put_state(env, "ml_item_visits", ids[3], checked_ago_days=5)

        result = run()

        rows = queue_rows(env)
        # performance has states for ids[0], ids[1]: the never-checked ids[2], ids[3] come first;
        # visits has states for ids[2], ids[3]: ids[0], ids[1] come first
        assert rows == {
            ids[2]: {"lane": queue.LANE_SWEEP, "resources": ["performance"]},
            ids[3]: {"lane": queue.LANE_SWEEP, "resources": ["performance"]},
            ids[0]: {"lane": queue.LANE_SWEEP, "resources": ["visits"]},
            ids[1]: {"lane": queue.LANE_SWEEP, "resources": ["visits"]},
        }
        assert result.outcome == sweeps.OUTCOME_SUCCESS and result.enqueued == 4

    def test_among_checked_items_the_least_recently_checked_goes_first(self, env) -> None:
        ids = put_items(env, 150)
        for n, item_id in enumerate(ids):
            put_state(env, "ml_item_performance", item_id, checked_ago_days=1 + n * 0.01)
        run(bundle=["core", "performance"])
        assert set(queue_rows(env)) == {ids[-1], ids[-2]}  # K = 2, the oldest two

    def test_each_resource_carries_only_its_own_name(self, env) -> None:
        ids = put_items(env, 3)
        put_state(env, "ml_item_visits", ids[0], checked_ago_days=1)
        put_state(env, "ml_item_visits", ids[1], checked_ago_days=1)
        put_state(env, "ml_item_performance", ids[2], checked_ago_days=1)
        run(bundle=["core", "performance"])
        assert {tuple(r["resources"]) for r in queue_rows(env).values()} == {("performance",)}
        with env.begin() as conn:
            conn.execute(text("DELETE FROM ml_pub_refresh_queue"))
        run(bundle=["core", "visits"])
        assert {tuple(r["resources"]) for r in queue_rows(env).values()} == {("visits",)}

    def test_closed_gone_and_never_existed_items_are_never_selected(self, env) -> None:
        put_items(env, 1, status="closed", prefix="MLC")
        put_items(env, 1, gone=True, prefix="MLG")
        put_items(env, 1, never_existed=True, prefix="MLN")
        kept = put_items(env, 1, prefix="MLK")
        result = run()
        assert set(queue_rows(env)) == set(kept)
        assert result.resources["performance"].eligible == 1

    def test_an_item_without_a_status_is_not_swept(self, env) -> None:
        with env.begin() as conn:
            conn.execute(text("INSERT INTO ml_items (item_id, http_status) VALUES ('MLX1', 200)"))
        run()
        assert queue_rows(env) == {}

    def test_the_status_setting_narrows_eligibility_and_the_batch_size_follows_it(self, env) -> None:
        put_items(env, 150, status="paused", prefix="MLP")
        active = put_items(env, 3, prefix="MLA")
        narrow = run(statuses=ACTIVE_ONLY)
        assert set(queue_rows(env)) == {active[0]}  # K = 1: the oldest active item, never a paused one
        assert narrow.resources["performance"].eligible == 3 and narrow.resources["performance"].batch == 1
        wide = run(statuses=EVERY_NON_CLOSED)
        assert wide.resources["performance"].eligible == 153 and wide.resources["performance"].batch == 2

    def test_the_default_setting_covers_every_non_closed_status(self, env) -> None:
        for status in EVERY_NON_CLOSED:
            put_items(env, 1, status=status, prefix=f"ML{status[:3]}")
        assert (
            run(statuses=sweeps.sweep_statuses(settings.ML_PUB_SWEEP_STATUSES)).resources["performance"].eligible == 5
        )

    def test_a_closed_status_in_the_setting_is_ignored_not_swept(self, env) -> None:
        put_items(env, 1, status="closed")
        assert sweeps.sweep_statuses(["closed", "active", "bogus"]) == ["active"]
        assert run(statuses=sweeps.sweep_statuses(["closed"])).resources["performance"].eligible == 0
        assert queue_rows(env) == {}

    def test_an_item_already_queued_is_left_alone_so_no_claim_is_bumped(self, env) -> None:
        ids = put_items(env, 2)
        queue_put(env, ids[0], queue.LANE_BACKFILL)
        run(bundle=["core", "visits"])
        rows = queue_rows(env)
        assert rows[ids[0]] == {"lane": queue.LANE_BACKFILL, "resources": ["bundle"]}
        assert rows[ids[1]]["resources"] == ["visits"]


class TestParkedEntries:
    def test_an_item_whose_entry_is_parked_is_not_eligible_so_it_neither_counts_nor_is_re_enqueued(self, env) -> None:
        parked, other = put_items(env, 2)
        queue_put(env, parked, queue.LANE_SWEEP, resources="{visits}")
        with env.begin() as conn:
            conn.execute(text("UPDATE ml_pub_refresh_queue SET parked_at = now()"))
        result = run(bundle=["core", "visits"])
        assert result.resources["visits"].eligible == 1  # the batch size is not inflated by an item it cannot reach
        assert set(queue_rows(env)) == {parked, other}
        assert queue_rows(env)[parked] == {"lane": queue.LANE_SWEEP, "resources": ["visits"]}  # untouched
        with env.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT version FROM ml_pub_refresh_queue WHERE entity_id = :i"), {"i": parked}
                ).scalar()
                == 1
            )

    def test_an_item_with_a_live_entry_still_counts_as_eligible(self, env) -> None:
        queued_item, _ = put_items(env, 2)
        queue_put(env, queued_item, queue.LANE_BACKFILL)
        assert run(bundle=["core", "visits"]).resources["visits"].eligible == 2


class TestNotApplicablePerformance:
    def test_it_is_skipped_until_the_recheck_interval_has_passed(self, env) -> None:
        recent, old = put_items(env, 2)
        put_state(env, "ml_item_performance", recent, checked_ago_days=29, applicable=False)
        put_state(env, "ml_item_performance", old, checked_ago_days=31, applicable=False)
        result = run(bundle=["core", "performance"], recheck_days=30)
        assert set(queue_rows(env)) == {old}
        assert result.resources["performance"].eligible == 1  # the one recheck-due item; K = 1

    def test_an_applicable_performance_state_is_swept_by_age_like_any_other(self, env) -> None:
        (item,) = put_items(env, 1)
        put_state(env, "ml_item_performance", item, checked_ago_days=1, applicable=True)
        run(bundle=["core", "performance"], recheck_days=30)
        assert set(queue_rows(env)) == {item}

    def test_the_interval_is_the_setting_not_a_constant(self, env) -> None:
        (item,) = put_items(env, 1)
        put_state(env, "ml_item_performance", item, checked_ago_days=10, applicable=False)
        run(bundle=["core", "performance"], recheck_days=30)
        assert queue_rows(env) == {}
        run(bundle=["core", "performance"], recheck_days=7)
        assert set(queue_rows(env)) == {item}

    def test_visits_of_the_same_item_are_still_swept(self, env) -> None:
        (item,) = put_items(env, 1)
        put_state(env, "ml_item_performance", item, checked_ago_days=1, applicable=False)
        run()
        assert queue_rows(env)[item]["resources"] == ["visits"]

    def test_the_default_recheck_is_thirty_days(self) -> None:
        assert settings.ML_PUB_NOT_APPLICABLE_RECHECK_DAYS == 30


class TestWhatTheBundleEnables:
    def test_only_the_resources_listed_in_bundle_resources_are_swept(self, env) -> None:
        put_items(env, 2)
        result = run(bundle=["core", "visits"])
        assert set(result.resources) == {"visits"}
        assert {tuple(r["resources"]) for r in queue_rows(env).values()} == {("visits",)}

    def test_nothing_listed_means_nothing_selected_and_the_tick_says_why(self, env) -> None:
        put_items(env, 2)
        result = run(bundle=["core"])
        assert queue_rows(env) == {} and result.outcome == sweeps.OUTCOME_NO_RESOURCES


class TestYieldsToLiveTraffic:
    def test_it_enqueues_nothing_while_notification_lane_work_is_claimable(self, env) -> None:
        put_items(env, 2)
        queue_put(env, "MLA999", queue.LANE_NOTIFICATION)
        result = run()
        assert result.outcome == sweeps.OUTCOME_YIELDED and result.enqueued == 0
        assert set(queue_rows(env)) == {"MLA999"}

    def test_a_manual_lane_entry_also_stops_the_sweep(self, env) -> None:
        put_items(env, 1)
        queue_put(env, "MLA999", queue.LANE_MANUAL)
        assert run().outcome == sweeps.OUTCOME_YIELDED

    def test_once_the_live_work_is_drained_the_next_tick_sweeps(self, env) -> None:
        put_items(env, 1)
        queue_put(env, "MLA999", queue.LANE_NOTIFICATION)
        assert run().outcome == sweeps.OUTCOME_YIELDED
        with env.begin() as conn:
            conn.execute(text("DELETE FROM ml_pub_refresh_queue WHERE entity_id = 'MLA999'"))
        assert run().outcome == sweeps.OUTCOME_SUCCESS and len(queue_rows(env)) == 1

    def test_a_debounced_notification_entry_is_not_claimable_yet_and_does_not_block(self, env) -> None:
        put_items(env, 1)
        queue_put(env, "MLA999", queue.LANE_NOTIFICATION, not_before_hours=1)
        assert run().outcome == sweeps.OUTCOME_SUCCESS

    def test_reconcile_and_backfill_work_do_not_block_the_sweep(self, env) -> None:
        put_items(env, 1)
        queue_put(env, "MLA997", queue.LANE_RECONCILE)
        queue_put(env, "MLA998", queue.LANE_BACKFILL)
        assert run().outcome == sweeps.OUTCOME_SUCCESS

    def test_a_parked_live_entry_does_not_block_it_forever(self, env) -> None:
        put_items(env, 1)
        queue_put(env, "MLA999", queue.LANE_NOTIFICATION)
        with env.begin() as conn:
            conn.execute(text("UPDATE ml_pub_refresh_queue SET parked_at = now()"))
        assert run().outcome == sweeps.OUTCOME_SUCCESS


class TestBacklogGuard:
    def test_it_stops_adding_work_while_the_refresh_has_not_drained_what_it_enqueued(self, env) -> None:
        put_items(env, 150)  # K = 2 per resource, so at most 3 ticks x 4 entries are allowed to wait
        for n in range(sweeps.BACKLOG_TICKS * 4):
            queue_put(env, f"MLQ{n:03d}", queue.LANE_SWEEP, resources="{visits}")
        result = run()
        assert result.outcome == sweeps.OUTCOME_BACKLOG and result.enqueued == 0

    def test_a_small_backlog_does_not_stop_it(self, env) -> None:
        put_items(env, 150)
        queue_put(env, "MLQ001", queue.LANE_SWEEP, resources="{visits}")
        assert run().outcome == sweeps.OUTCOME_SUCCESS


class TestRunRecord:
    def test_every_tick_leaves_a_record_with_counts_per_resource_and_the_sizing(self, env) -> None:
        put_items(env, 150)
        run()
        (record,) = run_records(env)
        assert record["outcome"] == "success" and record["scope"] == "performance,visits"
        counts = record["counts"]
        assert counts["enqueued"] == 4
        assert counts["resources"]["performance"] == {"eligible": 150, "batch": 2, "selected": 2}
        assert counts["calls_per_day"] == 2 * 2 * 144  # 2 resources x K = 2 x 144 ticks
        assert counts["requests_per_second"] == round(576 / 86_400, 4)

    def test_a_yielded_tick_is_recorded_too(self, env) -> None:
        put_items(env, 1)
        queue_put(env, "MLA999", queue.LANE_NOTIFICATION)
        run()
        assert run_records(env)[0]["outcome"] == "yielded"

    def test_an_unexpected_error_is_recorded_and_never_raised(self, env, monkeypatch) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("db is gone")

        monkeypatch.setattr(queue, "enqueue", boom)
        put_items(env, 1)
        result = run()
        assert result.error.startswith("internal_error: RuntimeError")
        assert run_records(env)[0]["outcome"] == "failed" and "db is gone" in run_records(env)[0]["last_error"]


class TestFetchedByNameThroughTheBundleGate:
    def test_both_resources_are_sweep_only_so_only_a_named_entry_reaches_them(self) -> None:
        from app.services.ml_publications import bundle

        assert bundle.SWEEP_ONLY == set(sweeps.SWEEP_RESOURCES)
        assert bundle.plan(["bundle"], ["core", *sweeps.SWEEP_RESOURCES]).wanted == {}
        for name in sweeps.SWEEP_RESOURCES:
            assert bundle.plan([name], ["core", *sweeps.SWEEP_RESOURCES]).wanted == {name: True}

    def test_visits_are_one_item_per_call(self) -> None:
        from app.services.ml_publications import bundle

        fetcher = bundle.FETCHERS["visits"]
        assert fetcher.path == "/items/{id}/visits/time_window" and fetcher.entity == "item"


class TestNoMlCallOfItsOwn:
    def test_the_sweep_module_never_touches_the_ml_client(self) -> None:
        from pathlib import Path

        source = Path(sweeps.__file__).read_text(encoding="utf-8")
        assert "MlHttpClient" not in source and "ml_http" not in source and ".get(" not in source
