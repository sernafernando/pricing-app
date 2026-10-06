"""Durable dirty queue (design D10): dedupe, lanes, single-flight claims, fencing, parking.

Postgres only: `FOR UPDATE SKIP LOCKED`, `gen_random_uuid()` and array merging
cannot be reproduced on SQLite. Queue entries are plain work items (ids and
lanes), not ML payloads.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from app.services.ml_publications import queue
from app.services.ml_publications.queue import EnqueueEntry, LaneFairness, claim, complete, enqueue, park, release

pytestmark = pytest.mark.postgres

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def entry(item: str, lane: int = 1, resources=("bundle",), **kwargs) -> EnqueueEntry:
    return EnqueueEntry(kind="item", entity_id=item, lane=lane, resources=tuple(resources), **kwargs)


def row(engine, item: str, kind: str = "item"):
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT * FROM ml_pub_refresh_queue WHERE kind = :k AND entity_id = :e"), {"k": kind, "e": item}
            )
            .mappings()
            .first()
        )


def count(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM ml_pub_refresh_queue")).scalar()


def sql(engine, statement: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(statement), params)


def claim_one(item: str, **kwargs):
    claims = claim(limit=50, worker_id="w1", kinds=["item"], **kwargs)
    return next(c for c in claims if c.entity_id == item)


class TestEnqueue:
    def test_five_enqueues_collapse_into_one_row(self, mlpub_pg) -> None:
        for _ in range(5):
            enqueue([entry("MLA1")])
        assert count(mlpub_pg) == 1
        stored = row(mlpub_pg, "MLA1")
        assert stored["version"] == 5
        assert list(stored["resources"]) == ["bundle"]

    def test_resources_are_merged_without_duplicates(self, mlpub_pg) -> None:
        enqueue([entry("MLA1", resources=("prices", "sale_price"))])
        enqueue([entry("MLA1", resources=("promotions", "prices"))])
        assert sorted(row(mlpub_pg, "MLA1")["resources"]) == ["prices", "promotions", "sale_price"]

    def test_enqueue_returns_the_number_of_entries_and_handles_a_batch(self, mlpub_pg) -> None:
        assert enqueue([entry("MLA1"), entry("MLA2"), entry("MLA1")]) == 3
        assert count(mlpub_pg) == 2
        assert row(mlpub_pg, "MLA1")["version"] == 2

    def test_empty_enqueue_is_a_noop(self, mlpub_pg) -> None:
        assert enqueue([]) == 0

    def test_source_received_at_keeps_the_oldest_notification(self, mlpub_pg) -> None:
        older = NOW() - timedelta(minutes=5)
        newer = NOW()
        enqueue([entry("MLA1", source_received_at=newer)])
        enqueue([entry("MLA1", source_received_at=older)])
        enqueue([entry("MLA1")])  # no timestamp must not erase it
        assert row(mlpub_pg, "MLA1")["source_received_at"] == older

    def test_lane_upgrade_keeps_one_row_with_the_higher_priority_lane_and_undelays_it(self, mlpub_pg) -> None:
        enqueue([entry("MLA1", lane=3, not_before=NOW() + timedelta(hours=1))])
        enqueue([entry("MLA1", lane=1)])
        stored = row(mlpub_pg, "MLA1")
        assert count(mlpub_pg) == 1
        assert stored["lane"] == 1
        assert stored["not_before"] <= NOW()

    def test_lower_priority_enqueue_never_downgrades_the_lane_or_moves_not_before(self, mlpub_pg) -> None:
        later = NOW() + timedelta(hours=1)
        enqueue([entry("MLA1", lane=1, not_before=later)])
        enqueue([entry("MLA1", lane=3, not_before=NOW())])
        enqueue([entry("MLA1", lane=1, not_before=NOW())])  # same lane: no un-delay either
        stored = row(mlpub_pg, "MLA1")
        assert stored["lane"] == 1
        assert stored["not_before"] > NOW() + timedelta(minutes=30)

    def test_a_notification_enqueue_does_not_unpark_a_parked_entry_but_a_manual_one_does(self, mlpub_pg) -> None:
        enqueue([entry("MLA1", lane=1)])
        sql(mlpub_pg, "UPDATE ml_pub_refresh_queue SET parked_at = now(), attempts = 8, last_error = 'boom'")
        enqueue([entry("MLA1", lane=1)])
        assert row(mlpub_pg, "MLA1")["parked_at"] is not None
        enqueue([entry("MLA1", lane=0)])
        stored = row(mlpub_pg, "MLA1")
        assert (stored["parked_at"], stored["attempts"], stored["lane"]) == (None, 0, 0)

    def test_kinds_do_not_collide(self, mlpub_pg) -> None:
        enqueue([EnqueueEntry("item", "X1", 1), EnqueueEntry("user_product", "X1", 1)])
        assert count(mlpub_pg) == 2


class TestClaim:
    def test_claim_returns_a_token_and_marks_the_entry_claimed(self, mlpub_pg) -> None:
        enqueue([entry("MLA1", resources=("prices", "bundle"), lane=2)])
        (got,) = claim(limit=10, worker_id="w1", kinds=["item"])
        assert (got.kind, got.entity_id, got.lane, got.version, got.attempts) == ("item", "MLA1", 2, 1, 0)
        assert got.resources == ("bundle", "prices")
        stored = row(mlpub_pg, "MLA1")
        assert (stored["claimed_by"], str(stored["claim_token"])) == ("w1", got.claim_token)
        assert claim(limit=10, worker_id="w2", kinds=["item"]) == []

    def test_claim_respects_limit_kinds_and_not_before(self, mlpub_pg) -> None:
        enqueue([entry(f"MLA{i}") for i in range(5)])
        enqueue([EnqueueEntry("family", "F1", 1)])
        enqueue([entry("MLA-LATER", not_before=NOW() + timedelta(hours=1))])
        got = claim(limit=3, worker_id="w1", kinds=["item"])
        assert len(got) == 3 and all(c.kind == "item" and c.entity_id != "MLA-LATER" for c in got)
        rest = claim(limit=50, worker_id="w1", kinds=["item"])
        assert len(rest) == 2

    def test_lane_priority_serves_notifications_before_backfill(self, mlpub_pg) -> None:
        enqueue([entry("BACKFILL", lane=3), entry("MANUAL", lane=0), entry("NOTIF", lane=1)])
        served = [claim(limit=1, worker_id="w1", kinds=["item"])[0].entity_id for _ in range(3)]
        assert served == ["MANUAL", "NOTIF", "BACKFILL"]

    def test_lanes_desc_serves_the_lowest_priority_first(self, mlpub_pg) -> None:
        enqueue([entry("NOTIF", lane=1), entry("BACKFILL", lane=3)])
        (got,) = claim(limit=1, worker_id="w1", kinds=["item"], lanes_desc=True)
        assert got.entity_id == "BACKFILL"

    def test_fairness_claims_a_backfill_entry_within_bounded_batches(self, mlpub_pg) -> None:
        enqueue([entry(f"LIVE{i}", lane=1) for i in range(30)] + [entry("BACKFILL", lane=3)])
        fair = LaneFairness(low_lane_min_share=0.1)
        order = []
        for _ in range(11):
            (got,) = claim(limit=1, worker_id="w1", kinds=["item"], lanes_desc=fair.next_lanes_desc())
            order.append(got.entity_id)
        assert order.index("BACKFILL") == 9  # the 10th batch is the low-lane batch
        assert all(name.startswith("LIVE") for name in order[:9])

    def test_fairness_share_controls_the_period(self) -> None:
        fair = LaneFairness(low_lane_min_share=0.25)
        assert [fair.next_lanes_desc() for _ in range(8)] == [False, False, False, True] * 2


class TestConcurrentClaims:
    def test_a_row_locked_by_another_transaction_is_skipped_not_waited_for(self, mlpub_pg) -> None:
        enqueue([entry("A"), entry("B"), entry("C")])
        holder = mlpub_pg.connect()
        trans = holder.begin()
        holder.execute(text("SELECT 1 FROM ml_pub_refresh_queue WHERE entity_id = 'A' FOR UPDATE"))
        result: list = []
        worker = threading.Thread(target=lambda: result.extend(claim(limit=10, worker_id="w1", kinds=["item"])))
        worker.start()
        worker.join(timeout=10)
        try:
            assert not worker.is_alive(), "claim blocked on a locked row: it must use SKIP LOCKED"
            assert sorted(c.entity_id for c in result) == ["B", "C"]
        finally:
            trans.rollback()
            holder.close()
            worker.join(timeout=10)

    def test_two_concurrent_claimers_never_share_an_entry(self, mlpub_pg) -> None:
        total = 120
        enqueue([entry(f"MLA{i:04d}") for i in range(total)])
        barrier = threading.Barrier(2)
        claimed: dict[str, list[str]] = {"w1": [], "w2": []}

        def drain(name: str) -> None:
            barrier.wait()
            while True:
                got = claim(limit=4, worker_id=name, kinds=["item"])
                if not got:
                    return
                claimed[name].extend(c.entity_id for c in got)

        threads = [threading.Thread(target=drain, args=(n,)) for n in claimed]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        everything = claimed["w1"] + claimed["w2"]
        assert len(everything) == total
        assert len(set(everything)) == total
        assert claimed["w1"] and claimed["w2"]  # both really participated


class TestCrashRecovery:
    def test_expired_claim_becomes_claimable_again_charging_one_attempt(self, mlpub_pg) -> None:
        enqueue([entry("MLA1")])
        first = claim_one("MLA1")
        sql(mlpub_pg, "UPDATE ml_pub_refresh_queue SET claimed_at = now() - interval '10 minutes'")
        second = claim_one("MLA1")
        assert second.claim_token != first.claim_token
        assert second.attempts == 1
        assert row(mlpub_pg, "MLA1")["last_error"] == "lease_expired"

    def test_a_live_claim_is_not_reclaimed_before_the_lease_expires(self, mlpub_pg) -> None:
        enqueue([entry("MLA1")])
        claim_one("MLA1")
        sql(mlpub_pg, "UPDATE ml_pub_refresh_queue SET claimed_at = now() - interval '2 minutes'")
        assert claim(limit=10, worker_id="w2", kinds=["item"]) == []

    def test_lease_length_is_configurable(self, mlpub_pg) -> None:
        enqueue([entry("MLA1")])
        claim_one("MLA1")
        sql(mlpub_pg, "UPDATE ml_pub_refresh_queue SET claimed_at = now() - interval '2 minutes'")
        assert len(claim(limit=10, worker_id="w2", kinds=["item"], lease_seconds=60)) == 1

    def test_a_stale_token_cannot_complete_a_reclaimed_entry(self, mlpub_pg) -> None:
        enqueue([entry("MLA1")])
        stale = claim_one("MLA1")
        sql(mlpub_pg, "UPDATE ml_pub_refresh_queue SET claimed_at = now() - interval '10 minutes'")
        fresh = claim_one("MLA1")
        assert complete(stale, succeeded={"bundle"}, failed={}) == "not_owner"
        assert row(mlpub_pg, "MLA1") is not None
        assert complete(fresh, succeeded={"bundle"}, failed={}) == "completed"
        assert row(mlpub_pg, "MLA1") is None

    def test_an_entry_expired_at_max_attempts_is_parked(self, mlpub_pg) -> None:
        enqueue([entry("MLA1")])
        claim_one("MLA1")
        sql(mlpub_pg, "UPDATE ml_pub_refresh_queue SET claimed_at = now() - interval '10 minutes', attempts = 2")
        assert claim(limit=10, worker_id="w2", kinds=["item"], max_attempts=3) == []
        stored = row(mlpub_pg, "MLA1")
        assert stored["parked_at"] is not None and stored["attempts"] == 3


class TestComplete:
    def test_success_with_unchanged_version_deletes_the_entry(self, mlpub_pg) -> None:
        enqueue([entry("MLA1")])
        got = claim_one("MLA1")
        assert complete(got, succeeded={"bundle"}, failed={}) == "completed"
        assert count(mlpub_pg) == 0

    def test_a_version_bump_while_claimed_keeps_the_entry_for_a_refetch(self, mlpub_pg) -> None:
        enqueue([entry("MLA1")])
        got = claim_one("MLA1")
        enqueue([entry("MLA1", resources=("prices",))])  # notification lands mid-flight
        assert complete(got, succeeded={"bundle"}, failed={}) == "requeued"
        stored = row(mlpub_pg, "MLA1")
        assert sorted(stored["resources"]) == ["bundle", "prices"]
        assert (stored["claimed_at"], stored["claim_token"], stored["attempts"]) == (None, None, 0)
        assert stored["version"] == got.version + 1

    def test_partial_success_narrows_resources_to_the_failed_set_with_backoff(self, mlpub_pg) -> None:
        enqueue([entry("MLA1", resources=("core", "prices", "promotions"))])
        got = claim_one("MLA1")
        outcome = complete(got, succeeded={"core"}, failed={"prices": "http 503", "promotions": "timeout"})
        assert outcome == "failed"
        stored = row(mlpub_pg, "MLA1")
        assert sorted(stored["resources"]) == ["prices", "promotions"]
        assert stored["attempts"] == 1
        assert "prices: http 503" in stored["last_error"] and "promotions: timeout" in stored["last_error"]
        assert stored["claimed_at"] is None
        assert stored["not_before"] > NOW() + timedelta(seconds=25)  # 2^1 * 30 s * jitter(0.5..1) >= 30 s
        assert claim(limit=10, worker_id="w1", kinds=["item"]) == []  # backed off

    def test_backoff_grows_with_attempts_and_is_capped_at_six_hours(self, mlpub_pg) -> None:
        enqueue([entry("MLA1")])
        sql(mlpub_pg, "UPDATE ml_pub_refresh_queue SET attempts = 6")
        got = claim_one("MLA1")
        complete(got, succeeded=set(), failed={"bundle": "x"}, max_attempts=99)
        stored = row(mlpub_pg, "MLA1")
        assert stored["attempts"] == 7
        delay = (stored["not_before"] - NOW()).total_seconds()
        assert 2**7 * 30 * 0.5 - 5 <= delay <= 6 * 3600 + 5

    def test_unreported_resources_stay_queued_without_charging_an_attempt(self, mlpub_pg) -> None:
        enqueue([entry("MLA1", resources=("core", "prices"))])
        got = claim_one("MLA1")
        assert complete(got, succeeded={"core"}, failed={}) == "partial"
        stored = row(mlpub_pg, "MLA1")
        assert (list(stored["resources"]), stored["attempts"], stored["claimed_at"]) == (["prices"], 0, None)

    def test_poison_entry_is_parked_after_max_attempts_with_its_last_error(self, mlpub_pg) -> None:
        enqueue([entry("POISON")])
        for expected_attempt in (1, 2, 3):
            sql(mlpub_pg, "UPDATE ml_pub_refresh_queue SET not_before = now()")
            got = claim_one("POISON")
            outcome = complete(got, succeeded=set(), failed={"bundle": "http 500"}, max_attempts=3)
            assert row(mlpub_pg, "POISON")["attempts"] == expected_attempt
        assert outcome == "parked"
        stored = row(mlpub_pg, "POISON")
        assert stored["parked_at"] is not None and "http 500" in stored["last_error"]
        sql(mlpub_pg, "UPDATE ml_pub_refresh_queue SET not_before = now()")
        assert claim(limit=10, worker_id="w1", kinds=["item"]) == []

    def test_explicit_park_records_the_error_and_is_fenced(self, mlpub_pg) -> None:
        enqueue([entry("MLA1")])
        got = claim_one("MLA1")
        park(got, "unparseable response")
        stored = row(mlpub_pg, "MLA1")
        assert stored["parked_at"] is not None and stored["last_error"] == "unparseable response"
        assert stored["claim_token"] is None
        enqueue([entry("MLA2")])
        other = claim_one("MLA2")
        sql(mlpub_pg, "UPDATE ml_pub_refresh_queue SET claim_token = gen_random_uuid() WHERE entity_id = 'MLA2'")
        park(other, "late")  # stale token: no effect
        assert row(mlpub_pg, "MLA2")["parked_at"] is None


class TestRelease:
    def test_release_after_a_429_does_not_charge_attempts_and_delays_the_entry(self, mlpub_pg) -> None:
        enqueue([entry("MLA1"), entry("MLA2")])
        claims = claim(limit=10, worker_id="w1", kinds=["item"])
        cooldown_until = NOW() + timedelta(seconds=30)
        release(claims, pending={}, not_before=cooldown_until)
        for item in ("MLA1", "MLA2"):
            stored = row(mlpub_pg, item)
            assert stored["attempts"] == 0 and stored["claimed_at"] is None and stored["claim_token"] is None
            assert stored["not_before"] == cooldown_until
        assert claim(limit=10, worker_id="w1", kinds=["item"]) == []

    def test_release_can_narrow_resources_to_what_is_still_pending(self, mlpub_pg) -> None:
        enqueue([entry("MLA1", resources=("core", "prices"))])
        (got,) = claim(limit=10, worker_id="w1", kinds=["item"])
        release([got], pending={("item", "MLA1"): {"prices"}}, not_before=NOW())
        assert list(row(mlpub_pg, "MLA1")["resources"]) == ["prices"]

    def test_release_never_narrows_over_a_newer_version(self, mlpub_pg) -> None:
        enqueue([entry("MLA1", resources=("core",))])
        (got,) = claim(limit=10, worker_id="w1", kinds=["item"])
        enqueue([entry("MLA1", resources=("prices",))])
        release([got], pending={("item", "MLA1"): {"core"}}, not_before=NOW())
        assert sorted(row(mlpub_pg, "MLA1")["resources"]) == ["core", "prices"]

    def test_release_with_a_stale_token_does_nothing(self, mlpub_pg) -> None:
        enqueue([entry("MLA1")])
        stale = claim_one("MLA1")
        sql(mlpub_pg, "UPDATE ml_pub_refresh_queue SET claim_token = gen_random_uuid(), claimed_by = 'w2'")
        release([stale], pending={}, not_before=NOW() + timedelta(hours=1))
        stored = row(mlpub_pg, "MLA1")
        assert stored["claimed_by"] == "w2" and stored["not_before"] <= NOW()


def test_queue_module_deletes_only_from_the_queue_table() -> None:
    source = Path(queue.__file__).read_text(encoding="utf-8")
    deleted = re.findall(r"DELETE\s+FROM\s+([a-z_]+)", source, flags=re.IGNORECASE)
    assert deleted == ["ml_pub_refresh_queue"]
    assert not re.search(r"TRUNCATE|DROP\s+TABLE", source, flags=re.IGNORECASE)
