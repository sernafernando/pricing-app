"""Scan engine (design D17): per-status enumeration, resumable progress, rescans, missing-from-scan.

Every ML body is a captured scan response (`scan_*_20261006.json`). The ONE shape the capture does
not contain is the final page of a scroll; the tests use the captured empty answer (`results: []`)
for it, which is how the engine recognises the end. A test that needs a transition mutates a deep
copy of a real body by exactly the field it names.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import queue, scans
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from tests.services.ml_publications.conftest import scan_body

ACTIVE = scan_body("active_page1")["results"]  # 5 real ids
ACTIVE_2 = scan_body("active_page2")["results"]
CLOSED = scan_body("closed_page1")["results"]
PENDING = scan_body("pending_page1")["results"]
PAUSED = scan_body("paused_page1")["results"]
NOW = datetime(2026, 10, 7, 3, 30, tzinfo=timezone.utc)


# --- pure rules (no database) -------------------------------------------------------------


class TestStatusMap:
    def test_pending_scan_returns_items_whose_body_status_is_inactive(self):
        assert scans.body_statuses("pending") == frozenset({"inactive"})

    def test_other_statuses_map_to_themselves(self):
        for status in ("active", "paused", "closed", "under_review", "inactive"):
            assert scans.body_statuses(status) == frozenset({status})


def stored(status="active", checked_ago_days=0.0, gone=False) -> scans.StoredItem:
    return scans.StoredItem(
        status=status,
        last_checked_at=NOW - timedelta(days=checked_ago_days),
        gone_at=NOW if gone else None,
    )


class TestWantsRefresh:
    def test_full_mode_enqueues_everything_in_the_backfill_lane(self):
        assert scans.lane_for(scans.MODE_FULL, "active", None, now=NOW, stale_days=7) == queue.LANE_BACKFILL
        assert scans.lane_for(scans.MODE_FULL, "active", stored(), now=NOW, stale_days=7) == queue.LANE_BACKFILL

    def test_rescan_enqueues_a_missing_item_in_the_reconcile_lane(self):
        assert scans.lane_for(scans.MODE_RESCAN, "active", None, now=NOW, stale_days=7) == queue.LANE_RECONCILE

    def test_rescan_enqueues_gone_stale_and_status_differing_items(self):
        for item in (stored(gone=True), stored(checked_ago_days=7.5), stored(status="paused")):
            assert scans.lane_for(scans.MODE_RESCAN, "active", item, now=NOW, stale_days=7) == queue.LANE_RECONCILE

    def test_rescan_skips_a_fresh_item_with_the_scanned_status(self):
        assert scans.lane_for(scans.MODE_RESCAN, "active", stored(checked_ago_days=6.9), now=NOW, stale_days=7) is None

    def test_an_item_never_checked_is_stale(self):
        item = scans.StoredItem(status="active", last_checked_at=None, gone_at=None)
        assert scans.lane_for(scans.MODE_RESCAN, "active", item, now=NOW, stale_days=7) == queue.LANE_RECONCILE

    def test_pending_scan_with_an_inactive_stored_status_is_not_a_status_difference(self):
        fresh_inactive = stored(status="inactive", checked_ago_days=1)
        assert scans.lane_for(scans.MODE_RESCAN, "pending", fresh_inactive, now=NOW, stale_days=7) is None
        # triangulation: the identity rule would have re-enqueued it; a genuinely different status still does
        assert scans.lane_for(scans.MODE_RESCAN, "pending", stored(status="active"), now=NOW, stale_days=7) == (
            queue.LANE_RECONCILE
        )


class TestCoveredBodyStatuses:
    def test_a_body_status_is_covered_only_when_every_scan_that_can_return_it_completed(self):
        assert scans.covered_body_statuses({"active", "paused"}) == {"active", "paused"}
        # `inactive` bodies come from the `inactive` AND the `pending` scan
        assert scans.covered_body_statuses({"inactive"}) == frozenset()
        assert scans.covered_body_statuses({"inactive", "pending"}) == {"inactive"}
        assert scans.covered_body_statuses({"pending"}) == frozenset()


# --- engine against Postgres --------------------------------------------------------------

pg = pytest.mark.postgres


class Ml:
    """A scripted ML scan endpoint: answers by (status, scroll_id) with `script`, else the captured empty page."""

    def __init__(self, script: Optional[Callable[[str, Optional[str], int], httpx.Response]] = None):
        self.requests: List[httpx.Request] = []
        self.script = script
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = request.url.params["status"]
        scroll = request.url.params.get("scroll_id")
        if self.script is not None:
            response = self.script(status, scroll, len(self.requests))
            if response is not None:
                return response
        return httpx.Response(200, json=scan_body("under_review_empty"))

    def calls(self) -> List[tuple]:
        return [(r.url.params["status"], r.url.params.get("scroll_id")) for r in self.requests]


def page(name: str) -> httpx.Response:
    return httpx.Response(200, json=scan_body(name))


def two_active_pages(status, scroll, n):
    if scroll is None:
        return page("active_page1")
    return page("active_page2") if scroll == scan_body("active_page1")["scroll_id"] else None


def invalid_scroll() -> httpx.Response:
    return httpx.Response(400, json=scan_body("invalid_scroll"))


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", "413658225")
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "1")
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    return mlpub_pg


def run(ml: Ml, *, statuses=("active",), mode=None, keep_going=lambda: True, now=lambda: NOW, **kwargs):
    client = MlHttpClient(
        pacer=Pacer(clock=FakeClock()),
        transport=ml.transport,
        token_loader=lambda: {"access_token": "tok", "expires_epoch": 9e12},
    )
    return scans.run_scan(
        client,
        seller_id="413658225",
        statuses=list(statuses),
        requested_mode=mode,
        stale_days=kwargs.pop("stale_days", 7),
        keep_going=keep_going,
        deadline=kwargs.pop("deadline", datetime.now(timezone.utc) + timedelta(seconds=60)),
        now=now,
        **kwargs,
    )


def put_item(engine, item_id, *, status="active", checked_ago_days=0.0, gone=False, seen_at=None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_items (item_id, status, last_checked_at, gone_at, last_scan_seen_at, http_status, "
                "fetched_at) VALUES (:id, :status, :checked, :gone, :seen, 200, :checked)"
            ),
            {
                "id": item_id,
                "status": status,
                "checked": NOW - timedelta(days=checked_ago_days),
                "gone": NOW if gone else None,
                "seen": seen_at,
            },
        )


def queue_rows(engine) -> Dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT entity_id, lane, resources, version FROM ml_pub_refresh_queue ORDER BY entity_id")
        ).fetchall()
    return {r[0]: {"lane": r[1], "resources": list(r[2]), "version": r[3]} for r in rows}


def scan_state(engine, status) -> dict:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM ml_pub_scan_state WHERE status = :s"), {"s": status}).mappings().first()
    return dict(row) if row else {}


@pg
class TestBackfill:
    def test_full_enumeration_follows_the_configured_order_and_records_counts(self, env):
        def script(status, scroll, n):
            if status == "closed" and scroll is None:
                return page("closed_page1")
            if status == "active" and scroll is None:
                return page("active_page1")
            if status == "active" and scroll == scan_body("active_page1")["scroll_id"]:
                return page("active_page2")
            return None  # the captured empty page ends the scroll

        ml = Ml(script)
        result = run(ml, statuses=["closed", "active"])

        statuses_called = [s for s, _ in ml.calls()]
        assert statuses_called[0] == "closed" and statuses_called.index("active") > statuses_called.index("closed")
        assert result.complete and result.mode == scans.MODE_FULL  # empty store -> backfill
        rows = queue_rows(env)
        assert set(rows) == set(CLOSED) | set(ACTIVE) | set(ACTIVE_2)
        assert {r["lane"] for r in rows.values()} == {queue.LANE_BACKFILL}
        assert rows[CLOSED[0]]["resources"] == ["bundle"]
        closed, active = scan_state(env, "closed"), scan_state(env, "active")
        assert (closed["enumerated"], closed["enqueued"], closed["pages"]) == (5, 5, 2)
        assert (active["enumerated"], active["enqueued"], active["pages"]) == (10, 10, 3)
        assert closed["completed_at"] is not None and active["completed_at"] is not None

    def test_the_scan_request_is_the_scroll_search_of_the_seller_with_limit_100(self, env):
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else None)
        run(ml)
        first = ml.requests[0].url
        assert first.path == "/users/413658225/items/search"
        assert dict(first.params) == {"search_type": "scan", "status": "active", "limit": "100"}
        assert ml.requests[1].url.params["scroll_id"] == scan_body("active_page1")["scroll_id"]

    def test_an_empty_status_completes_with_zero_and_no_second_call(self, env):
        ml = Ml(lambda status, scroll, n: page("under_review_empty"))
        result = run(ml, statuses=["under_review"])
        assert len(ml.requests) == 1
        state = scan_state(env, "under_review")
        assert (state["enumerated"], state["enqueued"], state["pages"]) == (0, 0, 1)
        assert state["completed_at"] is not None and not state["unsupported"]
        assert result.complete and queue_rows(env) == {}

    def test_resume_after_restart_continues_from_the_stored_scroll(self, env):
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else None)

        def stop_after_first_page():
            return len(ml.requests) < 1  # allowed before the first call only

        first = run(ml, keep_going=stop_after_first_page)
        assert first.stopped == "disabled" and not first.complete
        assert len(ml.requests) == 1
        stored_scroll = scan_state(env, "active")["scroll_id"]
        assert stored_scroll == scan_body("active_page1")["scroll_id"]
        versions = {k: v["version"] for k, v in queue_rows(env).items()}

        second = run(ml)  # "restart": a fresh run reads the stored progress
        assert second.complete
        assert ml.calls()[1] == ("active", stored_scroll)  # no new first-page request
        assert ("active", None) not in ml.calls()[1:]
        assert {k: v["version"] for k, v in queue_rows(env).items()} == versions  # nothing re-enqueued

    def test_pause_by_flag_stops_at_the_next_page_boundary_keeping_progress(self, env):
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else page("active_page2"))
        calls_allowed = iter([True, False])
        result = run(ml, keep_going=lambda: next(calls_allowed))
        assert result.stopped == "disabled" and not result.complete
        assert len(ml.requests) == 1
        state = scan_state(env, "active")
        assert (state["pages"], state["enumerated"], state["completed_at"]) == (1, 5, None)
        assert state["scroll_id"] == scan_body("active_page1")["scroll_id"]

    def test_scroll_expiry_restarts_the_status_and_records_the_restart(self, env):
        seen = {"expired": False}

        def script(status, scroll, n):
            if scroll is None:
                return page("active_page1")
            if not seen["expired"]:
                seen["expired"] = True
                return invalid_scroll()
            return None

        ml = Ml(script)
        result = run(ml)
        assert result.complete
        assert [s for _, s in ml.calls()][:3] == [None, scan_body("active_page1")["scroll_id"], None]
        state = scan_state(env, "active")
        assert state["restarts"] == 1 and state["completed_at"] is not None and state["last_error"] is None
        # counts describe the scroll that completed: the items read before the restart are not added twice
        assert (state["enumerated"], state["enqueued"]) == (5, 5)
        assert set(queue_rows(env)) == set(ACTIVE)  # already-enqueued items are deduped, not doubled

    def test_scroll_expiry_is_bounded_then_the_status_is_failed_and_the_next_one_runs(self, env):
        def script(status, scroll, n):
            if status == "active":
                return page("active_page1") if scroll is None else invalid_scroll()
            return page("closed_page1") if scroll is None else None

        ml = Ml(script)
        result = run(ml, statuses=["active", "closed"])
        active = scan_state(env, "active")
        assert active["restarts"] == scans.MAX_RESTARTS and active["completed_at"] is not None
        assert "scroll" in active["last_error"]
        active_calls = [c for c in ml.calls() if c[0] == "active"]
        assert len(active_calls) == 2 * (scans.MAX_RESTARTS + 1)  # first page + failing scroll, per attempt
        assert scan_state(env, "closed")["completed_at"] is not None  # the run moved on
        assert result.complete and result.failed_statuses == ["active"]

    def test_a_400_on_the_first_request_marks_the_status_unsupported_and_skips_it(self, env):
        def script(status, scroll, n):
            if status == "pending":
                return httpx.Response(400, json={"message": "bad status", "error": "bad_request", "status": 400})
            return page("closed_page1") if scroll is None else None

        ml = Ml(script)
        result = run(ml, statuses=["pending", "closed"])
        pending = scan_state(env, "pending")
        assert pending["unsupported"] is True and pending["completed_at"] is not None
        assert len([c for c in ml.calls() if c[0] == "pending"]) == 1
        assert set(queue_rows(env)) == set(CLOSED)
        assert result.complete and result.unsupported_statuses == ["pending"]

    def test_a_scroll_that_never_ends_is_cut_by_the_overrun_guard(self, env):
        body = scan_body("active_page1")  # total 7789 at limit 100 -> 78 pages; the endpoint never ends
        ml = Ml(lambda status, scroll, n: httpx.Response(200, json=body))
        result = run(ml)
        state = scan_state(env, "active")
        assert state["completed_at"] is not None and "overrun" in state["last_error"]
        assert len(ml.requests) < 100 and result.failed_statuses == ["active"]

    def test_a_malformed_page_stops_the_run_without_touching_progress(self, env):
        body = scan_body("active_page1")
        body["results"] = "not a list"  # the one field changed on a real body
        ml = Ml(lambda status, scroll, n: httpx.Response(200, json=body))
        result = run(ml)
        assert result.error == "malformed_scan_response" and not result.complete
        state = scan_state(env, "active")
        assert state["completed_at"] is None and state["pages"] == 0 and queue_rows(env) == {}

    def test_rate_limit_stops_the_run_keeping_progress(self, env):
        def script(status, scroll, n):
            return page("active_page1") if scroll is None else httpx.Response(429, headers={"retry-after": "1"})

        ml = Ml(script)
        result = run(ml)
        assert result.stopped == "rate_limited" and not result.complete and result.error is None
        assert scan_state(env, "active")["scroll_id"] == scan_body("active_page1")["scroll_id"]

    def test_missing_credentials_fail_closed_without_a_scan_call(self, env, monkeypatch):
        monkeypatch.setattr(settings, "ML_CLIENT_ID", None)
        ml = Ml()
        result = run(ml)
        assert ml.requests == [] and result.error == "not_configured" and not result.complete


@pg
class TestRescan:
    def rescan(self, ml: Ml, **kwargs):
        return run(ml, mode=scans.MODE_RESCAN, **kwargs)

    def test_only_missing_gone_stale_and_status_differing_items_are_enqueued(self, env):
        put_item(env, ACTIVE[0], checked_ago_days=1)  # fresh -> skipped
        put_item(env, ACTIVE[1], gone=True, checked_ago_days=1)  # gone -> enqueued
        put_item(env, ACTIVE[2], checked_ago_days=10)  # stale -> enqueued
        put_item(env, ACTIVE[3], status="paused", checked_ago_days=1)  # status differs -> enqueued
        # ACTIVE[4] is not stored at all -> missing -> enqueued
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else None)
        result = self.rescan(ml)
        rows = queue_rows(env)
        assert set(rows) == set(ACTIVE[1:])
        assert {r["lane"] for r in rows.values()} == {queue.LANE_RECONCILE}
        state = scan_state(env, "active")
        assert (state["enumerated"], state["enqueued"]) == (5, 4)
        assert result.mode == scans.MODE_RESCAN

    def test_fresh_items_are_skipped_entirely(self, env):
        for item_id in ACTIVE:
            put_item(env, item_id, checked_ago_days=1)
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else None)
        self.rescan(ml)
        assert queue_rows(env) == {}
        assert scan_state(env, "active")["enumerated"] == 5

    def test_pending_scan_does_not_requeue_fresh_inactive_items(self, env):
        for item_id in PENDING:
            put_item(env, item_id, status="inactive", checked_ago_days=1)
        ml = Ml(lambda status, scroll, n: page("pending_page1") if scroll is None else None)
        self.rescan(ml, statuses=["pending"])
        assert queue_rows(env) == {}
        assert scan_state(env, "pending")["enumerated"] == 5

    def test_last_scan_seen_at_is_a_narrow_update(self, env):
        put_item(env, ACTIVE[0], checked_ago_days=1)
        with env.connect() as conn:
            before = conn.execute(
                text("SELECT fetched_at, last_checked_at, status, http_status FROM ml_items WHERE item_id = :i"),
                {"i": ACTIVE[0]},
            ).one()
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else None)
        self.rescan(ml)
        with env.connect() as conn:
            after = conn.execute(
                text(
                    "SELECT fetched_at, last_checked_at, status, http_status, last_scan_seen_at FROM ml_items "
                    "WHERE item_id = :i"
                ),
                {"i": ACTIVE[0]},
            ).one()
        assert tuple(after[:4]) == tuple(before) and after[4] == NOW
        with env.connect() as conn:  # an item that is not stored is not invented by the scan
            assert conn.execute(text("SELECT count(*) FROM ml_items")).scalar() == 1


@pg
class TestMissingFromScan:
    def lap(self, ml, statuses=("active",), **kwargs):
        return run(ml, statuses=statuses, mode=scans.MODE_RESCAN, **kwargs)

    def test_a_stored_item_no_scan_returned_gets_a_direct_refresh_and_is_never_deleted(self, env):
        put_item(env, "MLA111", checked_ago_days=1)  # stored active, absent from the scan
        for item_id in ACTIVE:  # every returned item is stored and fresh: only MLA111 stands out
            put_item(env, item_id, checked_ago_days=1)
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else None)
        result = self.lap(ml)
        rows = queue_rows(env)
        assert set(rows) == {"MLA111"}
        assert rows["MLA111"]["lane"] == queue.LANE_RECONCILE and rows["MLA111"]["resources"] == ["core"]
        assert result.missing_enqueued == 1 and result.complete
        with env.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ml_items")).scalar() == 6

    def test_gone_items_and_statuses_the_lap_did_not_cover_are_left_alone(self, env):
        put_item(env, "MLA111", checked_ago_days=1, gone=True)
        put_item(env, "MLA222", status="paused", checked_ago_days=1)  # `paused` was not scanned
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else None)
        self.lap(ml)
        assert {"MLA111", "MLA222"}.isdisjoint(queue_rows(env))

    def test_a_failed_status_is_not_treated_as_missing_items(self, env):
        put_item(env, "MLA333", status="active", checked_ago_days=1)

        def script(status, scroll, n):
            return page("active_page1") if scroll is None else invalid_scroll()

        result = self.lap(Ml(script))
        assert result.failed_statuses == ["active"] and result.missing_enqueued == 0
        assert "MLA333" not in queue_rows(env)

    def test_the_pending_scan_covers_inactive_bodies_only_with_the_inactive_scan(self, env):
        put_item(env, "MLA444", status="inactive", checked_ago_days=1)
        ml = Ml(lambda status, scroll, n: page("pending_page1") if scroll is None else None)
        self.lap(ml, statuses=["pending"])  # `inactive` scan not part of the lap: inactive stays uncovered
        assert "MLA444" not in queue_rows(env)
        self.lap(ml, statuses=["pending", "inactive"])
        assert "MLA444" in queue_rows(env)


@pg
class TestLapsAndRecords:
    def test_the_first_lap_of_an_empty_store_is_a_backfill_and_a_later_one_a_rescan(self, env):
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else None)
        assert run(ml).mode == scans.MODE_FULL
        put_item(env, ACTIVE[0], checked_ago_days=1)
        assert run(ml).mode == scans.MODE_RESCAN  # previous lap complete -> a new one starts

    def test_a_completed_lap_starts_again_from_the_first_page(self, env):
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else None)
        run(ml)
        first_lap_calls = len(ml.requests)
        run(ml)
        assert ml.calls()[first_lap_calls] == ("active", None)
        assert scan_state(env, "active")["enumerated"] == 5  # counters were reset, not accumulated (10)

    def test_a_full_request_restarts_an_open_rescan_lap_as_full(self, env):
        put_item(env, ACTIVE[0], checked_ago_days=1)
        ml = Ml(two_active_pages)
        run(ml, keep_going=iter([True, False]).__next__)  # leaves a rescan lap open
        assert scan_state(env, "active")["completed_at"] is None
        calls_before = len(ml.requests)
        result = run(ml, mode=scans.MODE_FULL)
        assert ml.calls()[calls_before] == ("active", None)  # restarted
        assert result.mode == scans.MODE_FULL

    def test_a_requested_full_does_not_restart_a_lap_that_is_already_full(self, env):
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else None)
        run(ml, keep_going=iter([True, False]).__next__)
        calls_before = len(ml.requests)
        run(ml, mode=scans.MODE_FULL)
        assert ml.calls()[calls_before][1] == scan_body("active_page1")["scroll_id"]

    def test_the_lap_writes_one_run_record_that_closes_with_the_outcome_and_counts(self, env):
        ml = Ml(lambda status, scroll, n: page("closed_page1") if scroll is None else None)
        run(ml, keep_going=iter([True, False]).__next__, statuses=["closed"])
        with env.connect() as conn:
            open_rows = conn.execute(text("SELECT job, scope, finished_at FROM ml_pub_job_runs")).fetchall()
        assert [(r[0], r[1], r[2]) for r in open_rows] == [("scan", "full", None)]
        run(ml, statuses=["closed"])
        with env.connect() as conn:
            rows = conn.execute(text("SELECT job, scope, outcome, counts, finished_at FROM ml_pub_job_runs")).fetchall()
        assert len(rows) == 1 and rows[0][2] == "success" and rows[0][4] is not None
        assert rows[0][3]["enumerated"] == 5 and rows[0][3]["mode"] == "full"
        assert rows[0][3]["statuses"]["closed"]["enqueued"] == 5

    def test_a_lap_with_a_failed_status_closes_its_record_as_failed(self, env):
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else invalid_scroll())
        run(ml)
        with env.connect() as conn:
            row = conn.execute(text("SELECT outcome, last_error FROM ml_pub_job_runs")).one()
        assert row[0] == "failed" and "active" in row[1]

    def test_the_deadline_stops_the_run_between_pages(self, env):
        ml = Ml(lambda status, scroll, n: page("active_page1") if scroll is None else page("active_page2"))
        result = run(ml, deadline=datetime.now(timezone.utc) - timedelta(seconds=1))
        assert result.stopped == "deadline" and ml.requests == [] and not result.complete
