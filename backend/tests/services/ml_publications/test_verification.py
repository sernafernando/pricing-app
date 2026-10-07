"""Verification jobs (spec "Divergence spot-check", "Freshness and completeness metrics").

Postgres only. Every ML body is a captured item (`items_bulk_samples_20261006.json`); the stored copy and the
"fresh" ML answer start identical and a test that needs a difference mutates a deep copy by exactly one field
and says so. The ML side is an `httpx.MockTransport` behind the real `MlHttpClient` and a recording pacer, so
"lane 4 and shared pacing" is asserted through the pacer itself.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.ml_publications import MlItem
from app.services.ml_publications import queue, verification
from app.services.ml_publications.mappers import map_item
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from tests.services.ml_publications.conftest import sample_item

pytestmark = pytest.mark.postgres

ID_PREFIX = {"active": "MLA1", "paused": "MLA2", "closed": "MLA3"}
BASE_ITEMS = {"active": "MLA874027718", "paused": "MLA862580589", "closed": "MLA1207279308"}


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class RecordingPacer(Pacer):
    """The shared pacer, remembering every endpoint family that spent a slot."""

    def __init__(self) -> None:
        super().__init__(clock=FakeClock())
        self.families: List[str] = []

    def acquire(self, family, deadline=None):
        self.families.append(family)
        return super().acquire(family, deadline)


class MlTransport(httpx.BaseTransport):
    """Serves `/items/bulk?ids=...` from `bodies` (id -> item body); an id absent from it is a real 404 element."""

    def __init__(self, bodies: Dict[str, dict], status: int = 200, on_call: Optional[Callable[[int], None]] = None):
        self.bodies = bodies
        self.status = status
        self.on_call = on_call
        self.requests: List[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.on_call:
            self.on_call(len(self.requests))
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "boom"}, headers={"retry-after": "1"})
        elements = []
        for item_id in request.url.params["ids"].split(","):
            if item_id in self.bodies:
                elements.append({"id": item_id, "status_code": 200, "body": self.bodies[item_id]})
            else:
                elements.append({"id": item_id, "status_code": 404, "error": {"message": "not found"}})
        return httpx.Response(200, json=elements)


def make_client(transport: MlTransport, pacer: Optional[Pacer] = None) -> MlHttpClient:
    return MlHttpClient(
        pacer=pacer or RecordingPacer(),
        transport=transport,
        token_loader=lambda: {"access_token": "t", "expires_epoch": 9e12},
    )


def deadline() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=60)


def clone(base_status: str, item_id: str) -> dict:
    """A captured item body under another id (the only field changed)."""
    body = sample_item(BASE_ITEMS[base_status])
    body["id"] = item_id
    return body


def seed(engine, kinds: Dict[str, int]) -> Dict[str, dict]:
    """Store `n` copies of each captured status as `ml_items` rows built through the real mapper."""
    bodies: Dict[str, dict] = {}
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    with sessionmaker(bind=engine)() as session:
        for kind, count in kinds.items():
            for n in range(count):
                body = clone(kind, f"{ID_PREFIX[kind]}{n:05d}")
                bodies[body["id"]] = body
                session.add(
                    MlItem(
                        **map_item(body),
                        raw=body,
                        raw_hash=b"h",
                        http_status=200,
                        fetched_at=now,
                        last_checked_at=now,
                    )
                )
        session.commit()
    return bodies


def sql_all(engine, statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).mappings().all()


def check(client: MlHttpClient, **kw):
    kw.setdefault("sample_size", 100)
    kw.setdefault("bulk_max_ids", 20)
    kw.setdefault("deadline", deadline())
    kw.setdefault("keep_going", lambda: True)
    return verification.run_divergence(client, **kw)


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", "413658225")
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "7211863044554429")
    return mlpub_pg


class TestMatch:
    def test_100_identical_items_agree_at_100_percent(self, env) -> None:
        fresh = seed(env, {"active": 60, "paused": 25, "closed": 15})
        result = check(make_client(MlTransport(copy.deepcopy(fresh))))

        assert (result.sampled, result.compared, result.agreed) == (100, 100, 100)
        assert result.rate == 100.0
        assert result.divergences == []
        assert result.flagged is False
        assert result.outcome == verification.OUTCOME_SUCCESS

    def test_the_run_record_carries_rate_and_counts(self, env) -> None:
        fresh = seed(env, {"active": 5})
        check(make_client(MlTransport(fresh)), sample_size=5)

        (row,) = sql_all(env, "SELECT * FROM ml_pub_job_runs WHERE job = 'divergence'")
        assert row["outcome"] == "success" and row["last_error"] is None
        assert row["finished_at"] is not None
        assert row["counts"]["rate"] == 100.0 and row["counts"]["sampled"] == 5
        assert row["counts"]["below_target"] is False and row["counts"]["target"] == 99.0


class TestDivergence:
    def test_three_of_100_with_another_status_is_97_percent_flagged_with_the_three_pairs(self, env) -> None:
        fresh = seed(env, {"active": 60, "paused": 25, "closed": 15})
        changed = sorted(fresh)[:3]
        for item_id in changed:  # one field of a captured body: ML now answers `status` differently
            fresh[item_id]["status"] = "under_review" if fresh[item_id]["status"] != "under_review" else "active"

        result = check(make_client(MlTransport(fresh)))

        assert result.rate == 97.0
        assert result.flagged is True and result.outcome == verification.OUTCOME_BELOW_TARGET
        assert sorted((d["item_id"], d["path"]) for d in result.divergences) == [(i, "status") for i in changed]
        (row,) = sql_all(env, "SELECT * FROM ml_pub_job_runs WHERE job = 'divergence'")
        assert row["outcome"] == "below_target" and row["counts"]["below_target"] is True
        assert row["counts"]["rate"] == 97.0
        assert {(d["item_id"], d["path"]) for d in row["counts"]["divergences"]} == {(i, "status") for i in changed}

    def test_the_diverging_pair_shows_the_stored_and_the_fresh_value(self, env) -> None:
        fresh = seed(env, {"active": 1})
        (item_id,) = fresh
        fresh[item_id]["title"] = "Another title"

        (pair,) = check(make_client(MlTransport(fresh)), sample_size=1).divergences

        assert pair["path"] == "title" and pair["fresh"] == "Another title"
        assert pair["stored"] == sample_item(BASE_ITEMS["active"])["title"]

    def test_the_same_tags_in_another_order_are_not_divergence(self, env) -> None:
        fresh = seed(env, {"active": 1})
        (item_id,) = fresh
        fresh[item_id]["tags"] = list(reversed(fresh[item_id]["tags"]))  # same set, other order

        assert check(make_client(MlTransport(fresh)), sample_size=1).rate == 100.0

    def test_below_the_target_is_exactly_under_99(self, env) -> None:
        fresh = seed(env, {"active": 100})
        fresh[sorted(fresh)[0]]["status"] = "paused"

        result = check(make_client(MlTransport(fresh)))

        assert result.rate == 99.0
        assert result.flagged is False  # 99% is the target itself


class TestChangedAfterSampling:
    def test_a_store_refresh_after_sampling_is_not_divergence(self, env) -> None:
        fresh = seed(env, {"active": 10})
        moved = sorted(fresh)[0]
        fresh[moved]["status"] = "paused"

        def store_catches_up(call: int) -> None:  # the refresh handler stores the new state during our fetch
            with env.begin() as conn:
                conn.execute(
                    text("UPDATE ml_items SET status = 'paused', fetched_at = now() WHERE item_id = :i"), {"i": moved}
                )

        result = check(make_client(MlTransport(fresh, on_call=store_catches_up)), sample_size=10)

        assert result.divergences == []
        assert [(p["item_id"], p["path"]) for p in result.changed_after_sampling] == [(moved, "status")]
        assert (result.compared, result.agreed, result.rate) == (9, 9, 100.0)
        assert result.flagged is False

    def test_a_queued_refresh_marks_the_difference_as_pending_not_true_divergence(self, env) -> None:
        fresh = seed(env, {"active": 10})
        queued = sorted(fresh)[1]
        fresh[queued]["status"] = "paused"
        queue.enqueue([queue.EnqueueEntry("item", queued, queue.LANE_SWEEP)])  # its own lane does not stop the check

        result = check(make_client(MlTransport(fresh)), sample_size=10)

        assert result.divergences == [] and [p["item_id"] for p in result.changed_after_sampling] == [queued]

    def test_a_difference_with_nothing_queued_and_no_new_fetch_is_true_divergence(self, env) -> None:
        fresh = seed(env, {"active": 10})
        lost = sorted(fresh)[2]
        fresh[lost]["status"] = "paused"

        result = check(make_client(MlTransport(fresh)), sample_size=10)

        assert [d["item_id"] for d in result.divergences] == [lost] and result.changed_after_sampling == []


class TestSample:
    def test_it_covers_every_status_even_when_the_sample_is_small(self, env) -> None:
        fresh = seed(env, {"active": 40, "paused": 5, "closed": 3})
        transport = MlTransport(fresh)

        result = check(make_client(transport), sample_size=6)

        asked = {i for r in transport.requests for i in r.url.params["ids"].split(",")}
        statuses = {fresh[i]["status"] for i in asked}
        assert statuses == {"active", "paused", "closed"}
        assert result.sampled == 6 and sum(result.by_status.values()) == 6

    def test_it_never_asks_for_more_than_the_sample_or_for_unusable_rows(self, env) -> None:
        fresh = seed(env, {"active": 30})
        gone = sorted(fresh)[0]
        with env.begin() as conn:
            conn.execute(text("UPDATE ml_items SET gone_at = now() WHERE item_id = :i"), {"i": gone})
            conn.execute(text("INSERT INTO ml_items (item_id, status) VALUES ('MLA999', 'active')"))  # no raw yet
        transport = MlTransport(fresh)

        result = check(make_client(transport), sample_size=30)

        asked = [i for r in transport.requests for i in r.url.params["ids"].split(",")]
        assert gone not in asked and "MLA999" not in asked and len(asked) == len(set(asked)) == 29
        assert result.sampled == 29

    def test_an_empty_store_has_nothing_to_flag(self, env) -> None:
        transport = MlTransport({})

        result = check(make_client(transport))

        assert transport.requests == []
        assert (result.sampled, result.rate, result.flagged) == (0, None, False)
        assert result.outcome == verification.OUTCOME_SUCCESS

    def test_ids_per_call_respect_the_bulk_limit(self, env) -> None:
        fresh = seed(env, {"active": 45})
        transport = MlTransport(fresh)

        check(make_client(transport), sample_size=45, bulk_max_ids=20)

        assert [len(r.url.params["ids"].split(",")) for r in transport.requests] == [20, 20, 5]


class TestBudget:
    def test_every_call_spends_a_slot_of_the_shared_pacer_in_lane_4(self, env) -> None:
        fresh = seed(env, {"active": 60, "paused": 40})
        pacer = RecordingPacer()
        transport = MlTransport(fresh)

        result = check(make_client(transport, pacer))

        assert pacer.families == ["items_bulk"] * 5 == ["items_bulk"] * len(transport.requests)
        assert verification.LANE == queue.LANE_SWEEP == 4
        (row,) = sql_all(env, "SELECT counts FROM ml_pub_job_runs WHERE job = 'divergence'")
        assert row["counts"]["lane"] == 4 and row["counts"]["calls"] == 5
        assert result.calls == 5

    @pytest.mark.parametrize(
        "lane", [queue.LANE_MANUAL, queue.LANE_NOTIFICATION, queue.LANE_RECONCILE, queue.LANE_BACKFILL]
    )
    def test_it_yields_to_waiting_work_of_any_higher_lane(self, env, lane) -> None:
        fresh = seed(env, {"active": 5})
        queue.enqueue([queue.EnqueueEntry("item", "MLA1", lane)])
        transport = MlTransport(fresh)

        result = check(make_client(transport), sample_size=5)

        assert transport.requests == [] and result.outcome == verification.OUTCOME_YIELDED
        assert sql_all(env, "SELECT * FROM ml_pub_job_runs") == []

    def test_waiting_work_of_its_own_lane_does_not_stop_it(self, env) -> None:
        fresh = seed(env, {"active": 5})
        queue.enqueue([queue.EnqueueEntry("item", "MLA1", queue.LANE_SWEEP)])

        assert check(make_client(MlTransport(fresh)), sample_size=5).outcome == verification.OUTCOME_SUCCESS

    def test_a_429_stops_the_run_without_a_record(self, env) -> None:
        fresh = seed(env, {"active": 5})

        result = check(make_client(MlTransport(fresh, status=429)), sample_size=5)

        assert result.outcome == verification.OUTCOME_INTERRUPTED and result.interruption == "rate_limited"
        assert sql_all(env, "SELECT * FROM ml_pub_job_runs") == []

    def test_a_flag_turned_off_stops_it_at_the_next_batch(self, env) -> None:
        fresh = seed(env, {"active": 45})
        transport = MlTransport(fresh)
        flag = {"on": True}

        def turn_off(call: int) -> None:
            flag["on"] = False

        transport.on_call = turn_off
        result = check(make_client(transport), sample_size=45, keep_going=lambda: flag["on"])

        assert len(transport.requests) == 1
        assert result.outcome == verification.OUTCOME_INTERRUPTED and result.interruption == "flag_off"


class TestFailures:
    def test_a_server_error_is_recorded_with_its_error_and_never_raised(self, env) -> None:
        fresh = seed(env, {"active": 5})

        result = check(make_client(MlTransport(fresh, status=500)), sample_size=5)

        assert result.outcome == verification.OUTCOME_FAILED and "500" in result.error
        (row,) = sql_all(env, "SELECT * FROM ml_pub_job_runs WHERE job = 'divergence'")
        assert row["outcome"] == "failed" and "500" in row["last_error"]

    def test_an_item_ml_no_longer_knows_is_unverified_not_divergent(self, env) -> None:
        fresh = seed(env, {"active": 10})
        missing = sorted(fresh)[0]
        del fresh[missing]

        result = check(make_client(MlTransport(fresh)), sample_size=10)

        assert result.unverified == [{"item_id": missing, "http_status": 404}]
        assert (result.compared, result.rate, result.divergences) == (9, 100.0, [])


class TestSnapshot:
    def test_an_empty_store_gives_zeros_and_nulls_and_a_record(self, env) -> None:
        result = verification.run_snapshot(bundle_resources=["core"])

        assert result.outcome == verification.OUTCOME_SUCCESS
        (row,) = sql_all(env, "SELECT * FROM ml_pub_job_runs WHERE job = 'freshness'")
        counts = row["counts"]
        assert row["outcome"] == "success" and row["finished_at"] is not None
        assert counts["items"]["total"] == 0 and counts["items"]["by_status"] == {}
        assert counts["freshness"]["items"]["rows"] == 0 and counts["freshness"]["items"]["p95_age_seconds"] is None
        assert counts["lag_samples_24h"] == 0 and counts["lag_p95_seconds_24h"] is None
        assert counts["completeness"]["description"]["missing"] == 0

    def test_it_counts_the_store_with_the_status_queries(self, env) -> None:
        seed(env, {"active": 4, "paused": 2})

        verification.run_snapshot(bundle_resources=["core", "description"])

        (row,) = sql_all(env, "SELECT counts FROM ml_pub_job_runs WHERE job = 'freshness'")
        counts = row["counts"]
        assert counts["items"]["total"] == 6 and counts["items"]["with_raw"] == 6
        assert counts["items"]["by_status"] == {"active": 4, "paused": 2}
        assert counts["freshness"]["items"]["rows"] == 6
        assert counts["completeness"]["description"] == {"expected": True, "missing": 6, "non_2xx": {}}

    def test_the_snapshot_is_the_status_report_not_a_second_copy_of_it(self, env) -> None:
        from app.services.ml_publications import status

        seed(env, {"active": 3})
        with sessionmaker(bind=env)() as session:
            expected = status.freshness_metrics(session, ["core"])

        verification.run_snapshot(bundle_resources=["core"])

        (row,) = sql_all(env, "SELECT counts FROM ml_pub_job_runs WHERE job = 'freshness'")
        assert row["counts"]["items"] == expected["items"]
        assert row["counts"]["completeness"].keys() == expected["completeness"].keys()
