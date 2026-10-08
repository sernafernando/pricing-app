"""The replenishment branch of the sweep (P4b): keyed by user product, not by item.

Eligible: the DISTINCT user product (MLAU) of every stored item with `logistic_type = 'fulfillment'`, a sweep status
(never `closed`), not gone, never-existed excluded. K = ceil(eligible / 144) per tick, oldest state first. The
branch runs only when `replenishment` is listed in `bundle_resources`; the tick makes no ML call (the refresh
handler fetches what it enqueued, under the replenishment sub-gate). Items are plain rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import bundle, queue, sweeps

pytestmark = pytest.mark.postgres

ENABLED = ["core", "replenishment"]
EVERY_NON_CLOSED = ["active", "paused", "under_review", "inactive", "pending"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    return mlpub_pg


def run(*, bundle_resources=None, statuses=None):
    return sweeps.run_sweep(
        statuses=statuses or EVERY_NON_CLOSED,
        bundle_resources=ENABLED if bundle_resources is None else bundle_resources,
        recheck_days=30,
    )


def put_item(
    engine,
    item_id: str,
    up: Optional[str],
    *,
    logistic="fulfillment",
    status="active",
    gone=False,
    never_existed=False,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_items (item_id, status, logistic_type, user_product_id, gone_at, never_existed, "
                "http_status, last_checked_at) VALUES (:i, :s, :l, :up, :g, :n, 200, now())"
            ),
            {"i": item_id, "s": status, "l": logistic, "up": up, "g": utcnow() if gone else None, "n": never_existed},
        )


def put_ups(engine, count: int, *, prefix="MLAU1") -> List[str]:
    ups = [f"{prefix}{n:06d}" for n in range(count)]
    for n, up in enumerate(ups):
        put_item(engine, f"MLA{prefix}{n:06d}", up)
    return ups


def put_state(engine, up: str, *, checked_ago_days: Optional[float]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO ml_user_product_replenishment (user_product_id, last_checked_at) VALUES (:u, :c)"),
            {"u": up, "c": None if checked_ago_days is None else utcnow() - timedelta(days=checked_ago_days)},
        )


def queue_rows(engine) -> Dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT kind, entity_id, lane, resources FROM ml_pub_refresh_queue")).fetchall()
    return {r[1]: {"kind": r[0], "lane": r[2], "resources": list(r[3])} for r in rows}


def queue_up(engine, up: str, lane: int, *, parked=False) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_pub_refresh_queue (kind, entity_id, resources, lane, parked_at) "
                "VALUES ('user_product', :id, CAST('{bundle}' AS text[]), :lane, :parked)"
            ),
            {"id": up, "lane": lane, "parked": utcnow() if parked else None},
        )


class TestEligibility:
    def test_a_fulfillment_user_product_is_enqueued_by_its_own_id_in_the_sweep_lane_with_the_name(self, env) -> None:
        put_item(env, "MLA1", "MLAU1")
        result = run()
        assert queue_rows(env) == {
            "MLAU1": {"kind": "user_product", "lane": queue.LANE_SWEEP, "resources": ["replenishment"]}
        }
        assert result.error is None and result.enqueued == 1

    def test_only_fulfillment_items_count(self, env) -> None:
        put_item(env, "MLA1", "MLAU1", logistic="drop_off")
        put_item(env, "MLA2", "MLAU2", logistic="cross_docking")
        put_item(env, "MLA3", "MLAU3", logistic=None)
        assert run().resources["replenishment"].eligible == 0 and queue_rows(env) == {}

    def test_closed_gone_and_never_existed_items_are_not_eligible(self, env) -> None:
        put_item(env, "MLA1", "MLAU1", status="closed")
        put_item(env, "MLA2", "MLAU2", gone=True)
        put_item(env, "MLA3", "MLAU3", never_existed=True)
        put_item(env, "MLA4", "MLAU4", status=None)
        assert run().resources["replenishment"].eligible == 0 and queue_rows(env) == {}

    def test_the_status_setting_narrows_it(self, env) -> None:
        put_item(env, "MLA1", "MLAU1", status="active")
        put_item(env, "MLA2", "MLAU2", status="paused")
        assert run(statuses=["active"]).resources["replenishment"].eligible == 1
        assert set(queue_rows(env)) == {"MLAU1"}

    def test_an_item_without_a_user_product_is_skipped_without_error(self, env) -> None:
        put_item(env, "MLA1", None)
        put_item(env, "MLA2", "MLAU2")
        result = run()
        assert result.outcome == sweeps.OUTCOME_SUCCESS and result.error is None
        assert result.resources["replenishment"].eligible == 1 and set(queue_rows(env)) == {"MLAU2"}

    def test_items_sharing_a_user_product_make_one_entry(self, env) -> None:
        put_item(env, "MLA1", "MLAU1")
        put_item(env, "MLA2", "MLAU1")
        put_item(env, "MLA3", "MLAU1", status="closed")
        result = run()
        assert result.resources["replenishment"].eligible == 1 and list(queue_rows(env)) == ["MLAU1"]

    def test_a_user_product_with_one_closed_and_one_live_item_is_still_eligible(self, env) -> None:
        put_item(env, "MLA1", "MLAU1", status="closed")
        put_item(env, "MLA2", "MLAU1", status="active")
        assert run().resources["replenishment"].eligible == 1


class TestBatch:
    def test_k_is_the_ceiling_of_eligible_over_the_ticks_of_a_day(self, env) -> None:
        put_ups(env, 145)
        result = run()
        tick = result.resources["replenishment"]
        assert (tick.eligible, tick.batch, tick.selected) == (145, 2, 2)
        assert len(queue_rows(env)) == 2

    def test_never_checked_first_then_the_least_recently_checked(self, env) -> None:
        ups = put_ups(env, 3)
        put_state(env, ups[0], checked_ago_days=1)
        put_state(env, ups[1], checked_ago_days=5)
        # ups[2] never checked: first. K = 1 per tick for 3 eligible.
        run()
        assert set(queue_rows(env)) == {ups[2]}
        with env.begin() as conn:
            conn.execute(text("DELETE FROM ml_pub_refresh_queue"))
        put_state(env, ups[2], checked_ago_days=0)
        run()
        assert set(queue_rows(env)) == {ups[1]}  # 5 days old beats 1 day old

    def test_the_run_record_counts_it_beside_the_item_resources(self, env) -> None:
        put_ups(env, 3)
        run(bundle_resources=["core", "visits", "replenishment"])
        with env.connect() as conn:
            counts = conn.execute(text("SELECT counts FROM ml_pub_job_runs WHERE job = 'sweep'")).scalar()
        assert counts["resources"]["replenishment"] == {"eligible": 3, "batch": 1, "selected": 1}
        # one call per tick for replenishment (3 user products) and one for visits (3 items), 144 ticks a day
        assert counts["calls_per_day"] == 2 * 144


class TestQueueInteraction:
    def test_a_user_product_already_queued_is_left_alone(self, env) -> None:
        ups = put_ups(env, 2)
        queue_up(env, ups[0], queue.LANE_BACKFILL)
        queue_up(env, ups[1], queue.LANE_BACKFILL)
        run()
        assert {row["lane"] for row in queue_rows(env).values()} == {queue.LANE_BACKFILL}

    def test_an_item_entry_with_the_same_id_text_does_not_block_a_user_product(self, env) -> None:
        # the queue key is (kind, entity_id): an item entry never hides a user product
        put_item(env, "MLA1", "MLAU1")
        with env.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_pub_refresh_queue (kind, entity_id, resources, lane) "
                    "VALUES ('item', 'MLAU1', CAST('{bundle}' AS text[]), 3)"
                )
            )
        run()
        with env.connect() as conn:
            kinds = {
                r[0] for r in conn.execute(text("SELECT kind FROM ml_pub_refresh_queue WHERE entity_id = 'MLAU1'"))
            }
        assert kinds == {"item", "user_product"}

    def test_a_user_product_whose_entry_is_parked_is_not_eligible(self, env) -> None:
        parked, other = put_ups(env, 2)
        queue_up(env, parked, queue.LANE_SWEEP, parked=True)
        result = run()
        assert result.resources["replenishment"].eligible == 1
        assert set(queue_rows(env)) == {parked, other}


class TestGate:
    def test_it_runs_only_when_replenishment_is_listed_in_bundle_resources(self, env) -> None:
        put_ups(env, 2)
        result = run(bundle_resources=["core"])
        assert result.outcome == sweeps.OUTCOME_NO_RESOURCES and queue_rows(env) == {}
        result = run(bundle_resources=["core", "visits"])
        assert "replenishment" not in result.resources
        assert {row["kind"] for row in queue_rows(env).values()} == {"item"}  # visits only, no user product entry

    def test_it_is_one_of_the_swept_resources_and_sweep_only(self) -> None:
        assert "replenishment" in sweeps.SWEEP_RESOURCES
        assert bundle.SWEEP_ONLY == set(sweeps.SWEEP_RESOURCES)

    def test_it_yields_to_live_work_like_the_other_resources(self, env) -> None:
        put_ups(env, 1)
        with env.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_pub_refresh_queue (kind, entity_id, resources, lane) "
                    "VALUES ('item', 'MLAX', CAST('{bundle}' AS text[]), :lane)"
                ),
                {"lane": queue.LANE_NOTIFICATION},
            )
        assert run().outcome == sweeps.OUTCOME_YIELDED
        assert "MLAU1000000" not in queue_rows(env)
