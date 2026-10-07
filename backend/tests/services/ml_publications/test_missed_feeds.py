"""`/missed_feeds` recovery (design D17): paging, dedupe, the intake topic parser, the 48 h coverage gap.

Every ML body is the captured `/missed_feeds` answer (`missed_feeds_*_20261006.json`). The capture has a
single page with messages, so a second page with messages is built by changing the fields the test names on
deep copies of real messages (docstrings say which); the end of the list is the captured `{messages: null}`.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import intake, missed_feeds, queue
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from tests.services.ml_publications.conftest import missed_body

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
SELLER = "413658225"
MESSAGES = missed_body("items")["messages"]  # 3 real messages
IDS = ["MLA3510103662", "MLA4010366978", "MLA1854370497"]
ITEMS = intake.topic_mappings({"items": {"kind": "item", "resources": ["bundle"]}})
ITEMS_AND_PRICES = intake.topic_mappings(
    {
        "items": {"kind": "item", "resources": ["bundle"]},
        "items_prices": {"kind": "item", "resources": ["prices"]},
    }
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class Ml:
    """A scripted `/missed_feeds`: `pages` maps `(topic, offset)` to a body; anything else is the captured empty page."""

    def __init__(
        self, pages: Optional[Dict[tuple, dict]] = None, fail: Optional[Callable[[int], Optional[int]]] = None
    ):
        self.pages = pages if pages is not None else {("items", 0): missed_body("items")}
        self.fail = fail
        self.requests: List[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.fail(len(self.requests)) if self.fail else None
        if status:
            return httpx.Response(status, json={"message": "boom"})
        params = request.url.params
        return httpx.Response(
            200, json=self.pages.get((params["topic"], int(params.get("offset", 0))), missed_body("empty"))
        )

    def calls(self) -> List[tuple]:
        return [(r.url.params["topic"], int(r.url.params.get("offset", 0))) for r in self.requests]


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
    with mlpub_pg.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE worker_job_state (name varchar(64) PRIMARY KEY, last_run_at timestamptz, "
                "last_success_at timestamptz, state varchar(32), detail jsonb, heartbeat_at timestamptz)"
            )
        )
    monkeypatch.setattr(settings, "ML_USER_ID", SELLER)
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "7211863044554429")
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    return mlpub_pg


def run(ml: Ml, *, mappings=ITEMS, keep_going=lambda: True, resume=None, deadline=None, seller=SELLER):
    client = MlHttpClient(
        pacer=Pacer(clock=FakeClock()),
        transport=ml.transport,
        token_loader=lambda: {"access_token": "tok", "expires_epoch": 9e12},
    )
    return missed_feeds.run_missed_feeds(
        client,
        seller_id=seller,
        app_id="7211863044554429",
        mappings=mappings,
        keep_going=keep_going,
        deadline=deadline or datetime.now(timezone.utc) + timedelta(seconds=60),
        resume=resume,
        now=lambda: NOW,
    )


def queue_rows(engine) -> Dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT entity_id, lane, resources, source_received_at, version FROM ml_pub_refresh_queue")
        ).fetchall()
    return {r[0]: {"lane": r[1], "resources": list(r[2]), "received": r[3], "version": r[4]} for r in rows}


def run_records(engine) -> List[dict]:
    with engine.connect() as conn:
        rows = (
            conn.execute(text("SELECT * FROM ml_pub_job_runs WHERE job = 'missed_feeds' ORDER BY id")).mappings().all()
        )
    return [dict(r) for r in rows]


def scan_requested(engine) -> bool:
    with engine.connect() as conn:
        state = conn.execute(text("SELECT state FROM worker_job_state WHERE name = 'ml_publications.scan'")).scalar()
    return state == "requested"


def previous_success(engine, *, ago_hours: float) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_pub_job_runs (job, scope, started_at, finished_at, outcome, counts) "
                "VALUES ('missed_feeds', 'items', :at, :at, 'success', '{}')"
            ),
            {"at": NOW - timedelta(hours=ago_hours)},
        )


def with_message(**changes) -> dict:
    """A deep copy of the first real message with exactly the named fields changed."""
    message = copy.deepcopy(MESSAGES[0])
    message.update(changes)
    return message


class TestRecovery:
    def test_a_missed_event_is_enqueued_in_the_reconcile_lane_with_the_topic_resources(self, env):
        result = run(Ml())

        rows = queue_rows(env)
        assert set(rows) == set(IDS)
        assert {r["lane"] for r in rows.values()} == {queue.LANE_RECONCILE}
        assert {tuple(r["resources"]) for r in rows.values()} == {("bundle",)}
        assert rows["MLA3510103662"]["received"] == datetime(2026, 10, 5, 11, 5, 27, tzinfo=timezone.utc)
        assert result.complete and result.enqueued == 3 and result.messages == 3

    def test_the_request_is_app_and_topic_scoped_for_site_mla_with_a_page_limit(self, env):
        ml = Ml()
        run(ml)
        first = ml.requests[0].url
        assert first.path == "/missed_feeds"
        assert dict(first.params) == {
            "app_id": "7211863044554429",
            "topic": "items",
            "site_id": "MLA",
            "limit": str(missed_feeds.PAGE_LIMIT),
            "offset": "0",
        }

    def test_the_resource_goes_through_the_same_parser_as_intake_not_a_second_mapping(self, env):
        priced = with_message(topic="items_prices", resource="/items/MLA3510103662/prices")
        ml = Ml({("items_prices", 0): {"messages": [priced]}})
        run(ml, mappings=ITEMS_AND_PRICES)
        assert intake.parse_resource("items_prices", priced["resource"]) == "MLA3510103662"
        assert queue_rows(env)["MLA3510103662"]["resources"] == ["prices"]

    def test_an_empty_page_ends_paging_with_a_single_call(self, env):
        ml = Ml({})
        result = run(ml)
        assert ml.calls() == [("items", 0)]
        assert result.complete and result.enqueued == 0 and queue_rows(env) == {}

    def test_every_page_is_consumed_and_each_resource_is_enqueued_once(self, env):
        """Page 2 repeats the resource of the first real message under a new `_id` and adds the second real
        message's resource under a third id."""
        page2 = {
            "messages": [
                with_message(_id="00000000-0000-4000-8000-000000000001"),
                {**copy.deepcopy(MESSAGES[1]), "_id": "00000000-0000-4000-8000-000000000002"},
            ]
        }
        ml = Ml({("items", 0): missed_body("items"), ("items", missed_feeds.PAGE_LIMIT): page2})
        result = run(ml)

        assert ml.calls() == [("items", 0), ("items", missed_feeds.PAGE_LIMIT), ("items", 2 * missed_feeds.PAGE_LIMIT)]
        assert set(queue_rows(env)) == set(IDS)
        assert all(r["version"] == 1 for r in queue_rows(env).values())  # never bumped by a repeat
        assert (result.messages, result.enqueued, result.duplicates, result.pages) == (5, 3, 2, 2)

    def test_a_page_the_endpoint_keeps_answering_ends_the_topic_instead_of_looping(self, env):
        ml = Ml(
            {
                ("items", offset): missed_body("items")
                for offset in range(0, 100 * missed_feeds.PAGE_LIMIT, missed_feeds.PAGE_LIMIT)
            }
        )
        result = run(ml)
        assert len(ml.requests) == 1 + missed_feeds.REPEATED_PAGES_LIMIT
        assert result.complete and result.repeated_pages == missed_feeds.REPEATED_PAGES_LIMIT

    def test_one_page_made_only_of_seen_messages_does_not_end_the_topic_when_the_list_moved(self, env):
        """The list grew at the front between two requests, so page 2 shows page 1 again; page 3 has a new item
        (a deep copy of the first real message with a new `_id` and the second real message's resource)."""
        fresh = {"messages": [with_message(_id="00000000-0000-4000-8000-0000000000aa", resource="/items/MLA1")]}
        ml = Ml(
            {
                ("items", 0): missed_body("items"),
                ("items", missed_feeds.PAGE_LIMIT): missed_body("items"),
                ("items", 2 * missed_feeds.PAGE_LIMIT): fresh,
            }
        )
        result = run(ml)
        assert set(queue_rows(env)) == {*IDS, "MLA1"}
        assert result.complete and result.repeated_pages == 1

    def test_messages_without_an_id_are_still_recognised_as_a_repeated_page(self, env):
        """The captured messages with `_id` removed (the only change): ML answering the same page forever."""
        anonymous = {"messages": [{k: v for k, v in m.items() if k != "_id"} for m in missed_body("items")["messages"]]}
        ml = Ml(
            {
                ("items", offset): anonymous
                for offset in range(0, 100 * missed_feeds.PAGE_LIMIT, missed_feeds.PAGE_LIMIT)
            }
        )
        result = run(ml)
        assert len(ml.requests) == 1 + missed_feeds.REPEATED_PAGES_LIMIT
        assert result.complete and result.repeated_pages == missed_feeds.REPEATED_PAGES_LIMIT
        assert set(queue_rows(env)) == set(IDS)

    def test_each_mapped_topic_is_walked_in_order(self, env):
        ml = Ml()
        run(ml, mappings=ITEMS_AND_PRICES)
        assert ml.calls() == [("items", 0), ("items", missed_feeds.PAGE_LIMIT), ("items_prices", 0)]

    def test_other_sellers_and_unparsable_resources_are_counted_not_enqueued(self, env):
        foreign = with_message(_id="a", user_id="999")
        garbage = with_message(_id="b", resource="/orders/123")
        ml = Ml({("items", 0): {"messages": [foreign, garbage, "not-an-object"]}})
        result = run(ml)
        assert queue_rows(env) == {}
        assert (result.foreign, result.unparsed) == (1, 2)

    def test_a_foreign_message_does_not_hide_the_same_resource_from_the_seller(self, env):
        """The first real message with `user_id` changed to another seller, then the unchanged one."""
        foreign = with_message(_id="a", user_id="999")
        own = with_message(_id="b")
        result = run(Ml({("items", 0): {"messages": [foreign, own]}}))
        assert set(queue_rows(env)) == {"MLA3510103662"}
        assert (result.foreign, result.duplicates, result.enqueued) == (1, 0, 1)

    def test_a_later_delivery_of_an_item_already_satisfied_by_an_earlier_one_is_still_evaluated(self, env):
        """The item was fetched on 2026-10-06, so the real delivery of 2026-10-05 needs nothing; page 2 repeats the
        resource under a new `_id` with `received` changed to 2026-10-07, which is newer than that fetch."""
        with env.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_items (item_id, status, http_status, fetched_request_started_at) "
                    "VALUES ('MLA3510103662', 'active', 200, :at)"
                ),
                {"at": datetime(2026, 10, 6, tzinfo=timezone.utc)},
            )
        later = with_message(_id="00000000-0000-4000-8000-0000000000bb", received="2026-10-07T00:00:00Z")
        ml = Ml({("items", 0): missed_body("items"), ("items", missed_feeds.PAGE_LIMIT): {"messages": [later]}})
        result = run(ml)
        assert "MLA3510103662" in queue_rows(env)
        assert (result.satisfied, result.duplicates) == (1, 0)

    def test_an_item_fetched_after_the_missed_delivery_needs_no_refresh(self, env):
        with env.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_items (item_id, status, http_status, fetched_request_started_at) "
                    "VALUES ('MLA3510103662', 'active', 200, :at)"
                ),
                {"at": datetime(2026, 10, 6, tzinfo=timezone.utc)},
            )
        result = run(Ml())
        assert set(queue_rows(env)) == {"MLA4010366978", "MLA1854370497"}
        assert result.satisfied == 1


class TestNothingOfTheDeliveryIsStored:
    def test_the_request_and_response_of_the_delivery_attempt_reach_no_table(self, env):
        run(Ml())
        with env.connect() as conn:
            dump = json.dumps(
                {
                    "queue": [dict(r) for r in conn.execute(text("SELECT * FROM ml_pub_refresh_queue")).mappings()],
                    "runs": [dict(r) for r in conn.execute(text("SELECT * FROM ml_pub_job_runs")).mappings()],
                },
                default=str,
            )
        for fragment in ("ml-webhook.gaussonline", "req_time", "http_code", "recieved", MESSAGES[0]["_id"]):
            assert fragment not in dump


class TestRunRecord:
    def test_a_completed_run_leaves_a_record_with_counts_and_outcome(self, env):
        run(Ml())
        (record,) = run_records(env)
        assert record["outcome"] == "success" and record["scope"] == "items"
        assert record["started_at"] == NOW and record["finished_at"] == NOW
        counts = record["counts"]
        assert (counts["pages"], counts["messages"], counts["enqueued"]) == (1, 3, 3)
        assert counts["requests"] == {"2xx": 2}  # the page and the captured empty page that ends the list

    def test_a_failing_page_is_recorded_and_enqueues_nothing_from_it(self, env):
        result = run(Ml(fail=lambda n: 503))
        (record,) = run_records(env)
        assert result.error == "http_503" and not result.complete
        assert record["outcome"] == "failed" and record["last_error"] == "http_503"
        assert queue_rows(env) == {}
        assert result.resume == {"topic": "items", "offset": 0}

    def test_a_429_stops_the_run_keeping_the_position_and_is_not_a_failure(self, env):
        second_page_limited = lambda n: 429 if n == 2 else None  # noqa: E731
        ml = Ml({("items", 0): missed_body("items")}, fail=second_page_limited)
        result = run(ml)
        assert result.stopped == missed_feeds.STOP_RATE_LIMITED and result.error is None
        assert result.resume == {"topic": "items", "offset": missed_feeds.PAGE_LIMIT}
        assert set(queue_rows(env)) == set(IDS)  # the first page was applied
        assert run_records(env)[0]["outcome"] == "partial"

    def test_an_unexpected_error_while_applying_a_page_keeps_the_position_of_that_page(self, env, monkeypatch):
        real = queue.enqueue
        calls = {"n": 0}

        def second_page_fails(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("db is gone")
            return real(*args, **kwargs)

        monkeypatch.setattr(queue, "enqueue", second_page_fails)
        page2 = {"messages": [with_message(_id="00000000-0000-4000-8000-000000000009", resource="/items/MLA1")]}
        result = run(Ml({("items", 0): missed_body("items"), ("items", missed_feeds.PAGE_LIMIT): page2}))
        assert result.error.startswith("internal_error") and not result.complete
        assert result.resume == {"topic": "items", "offset": missed_feeds.PAGE_LIMIT}
        assert run_records(env)[0]["counts"]["resume"] == result.resume

    def test_a_gap_marker_survives_a_failed_record_so_the_rescan_is_not_requested_again(self, env, monkeypatch):
        previous_success(env, ago_hours=72)
        monkeypatch.setattr(missed_feeds, "_record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no write")))
        run(Ml())
        assert scan_requested(env)
        with env.begin() as conn:
            conn.execute(text("UPDATE worker_job_state SET state = NULL"))
        run(Ml())
        assert not scan_requested(env)

    def test_an_error_before_the_first_page_keeps_the_position_the_run_was_given(self, env, monkeypatch):
        monkeypatch.setattr(missed_feeds, "_detect_gap", lambda now: (_ for _ in ()).throw(RuntimeError("db is gone")))
        given = {"topic": "items", "offset": 40}
        result = run(Ml(), resume=given)
        assert result.error.startswith("internal_error") and result.resume == given

    def test_a_completed_run_has_no_position_left(self, env):
        assert run(Ml()).resume is None

    def test_a_run_resumes_at_the_stored_topic_and_offset(self, env):
        ml = Ml()
        run(ml, mappings=ITEMS_AND_PRICES, resume={"topic": "items_prices", "offset": 40})
        assert ml.calls() == [("items_prices", 40)]

    def test_a_flag_turned_off_between_pages_stops_the_run_with_its_position(self, env):
        allowed = iter([True, False])
        result = run(Ml(), keep_going=lambda: next(allowed))
        assert result.stopped == missed_feeds.STOP_DISABLED
        assert result.resume == {"topic": "items", "offset": missed_feeds.PAGE_LIMIT}

    def test_an_expired_deadline_calls_nothing(self, env):
        ml = Ml()
        result = run(ml, deadline=datetime.now(timezone.utc) - timedelta(seconds=1))
        assert ml.requests == [] and result.stopped == missed_feeds.STOP_DEADLINE
        assert result.resume == {"topic": "items", "offset": 0}

    def test_an_unexpected_error_is_recorded_and_never_raised(self, env, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("db is gone")

        monkeypatch.setattr(queue, "enqueue", boom)
        result = run(Ml())
        assert result.error.startswith("internal_error: RuntimeError")
        assert run_records(env)[0]["outcome"] == "failed"

    def test_a_missing_credential_is_reported_by_the_client_outcome(self, env, monkeypatch):
        monkeypatch.setattr(settings, "ML_CLIENT_ID", None)
        result = run(Ml())
        assert result.error == "not_configured" and run_records(env)[0]["outcome"] == "failed"


class TestCoverageGap:
    def test_a_last_success_older_than_48_hours_records_the_gap_and_requests_a_rescan(self, env):
        previous_success(env, ago_hours=72)
        run(Ml())
        record = run_records(env)[-1]
        assert record["counts"]["coverage_gap"]["hours"] == 72.0
        assert record["counts"]["coverage_gap"]["last_success_at"] == (NOW - timedelta(hours=72)).isoformat()
        assert scan_requested(env)

    def test_a_gap_is_requested_even_when_this_run_fails(self, env):
        previous_success(env, ago_hours=72)
        run(Ml(fail=lambda n: 500))
        assert scan_requested(env) and "coverage_gap" in run_records(env)[-1]["counts"]

    def test_the_rescan_is_requested_once_per_gap_not_on_every_retry(self, env):
        previous_success(env, ago_hours=72)
        run(Ml(fail=lambda n: 500))
        with env.begin() as conn:
            conn.execute(text("UPDATE worker_job_state SET state = NULL"))
        run(Ml(fail=lambda n: 500))
        assert not scan_requested(env)
        assert "coverage_gap" not in run_records(env)[-1]["counts"]

    def test_within_48_hours_there_is_no_gap(self, env):
        previous_success(env, ago_hours=47)
        run(Ml())
        assert "coverage_gap" not in run_records(env)[-1]["counts"] and not scan_requested(env)

    def test_the_first_run_has_nothing_to_compare_with(self, env):
        run(Ml())
        assert "coverage_gap" not in run_records(env)[-1]["counts"] and not scan_requested(env)

    def test_a_failed_or_partial_run_does_not_count_as_the_last_success(self, env):
        previous_success(env, ago_hours=72)
        with env.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_pub_job_runs (job, started_at, finished_at, outcome, counts) "
                    "VALUES ('missed_feeds', :at, :at, 'failed', '{}')"
                ),
                {"at": NOW - timedelta(hours=1)},
            )
        run(Ml())
        assert scan_requested(env)

    def test_the_request_does_not_touch_the_scan_mode_setting(self, env):
        previous_success(env, ago_hours=72)
        run(Ml())
        with env.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ml_pub_settings WHERE key = 'scan.next_mode'")).scalar() == 0
