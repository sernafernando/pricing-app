"""ml-ads-cupones-display T3a -- one ingestion run against Postgres with a fake ML client."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import select

from app.models.ml_order_discounts import MlOrderDiscountLine, MlOrderDiscounts, MlOrderDiscountsState
from app.models.ml_payments import MlPaymentOps
from app.services.ml_order_discounts import ingestion, store
from app.services.ml_publications.ml_http import OUTCOME_NO_TOKEN, MlResponse
from app.services.ml_publications.pacing import DEADLINE
from tests.services.ml_order_discounts.conftest import fixture

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


def response(status: int, body: Any = None, *, error: Optional[str] = None, headers: Optional[Dict[str, str]] = None):
    return MlResponse(
        endpoint=ingestion.FAMILY,
        status=status,
        body=body,
        headers=headers or {},
        request_started_at=NOW,
        received_at=NOW,
        error=error,
    )


class FakeClient:
    def __init__(self, answers: Dict[int, MlResponse]) -> None:
        self.answers = answers
        self.paths: List[str] = []

    def get(self, family: str, path: str, params: Any = None, **kwargs: Any) -> MlResponse:
        assert family == ingestion.FAMILY
        self.paths.append(path)
        order_id = int(path.split("/")[2])
        return self.answers[order_id]


def payment(db, payment_id: int, order_id: int, coupon: Optional[str], status: str = "approved", minutes: int = 0):
    db.add(
        MlPaymentOps(
            payment_id=payment_id,
            order_id=order_id,
            status=status,
            coupon_amount=None if coupon is None else Decimal(coupon),
            date_approved=NOW - timedelta(days=1) + timedelta(minutes=minutes),
        )
    )


def run(session_factory, client, max_calls: int = 30):
    return ingestion.run(
        session_factory, client, now=lambda: NOW, deadline=NOW + timedelta(seconds=20), max_calls=max_calls
    )


def rows(session_factory, model):
    with session_factory() as db:
        return db.execute(select(model)).scalars().all()


class TestPendingOrders:
    def test_only_orders_with_a_coupon_in_a_relevant_status_newest_first_once(self, session_factory) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "500.00", minutes=1)
            payment(db, 2, 100, "500.00", status="refunded", minutes=2)  # same order: asked for once
            payment(db, 3, 200, "10.00", minutes=5)  # newest
            payment(db, 4, 300, None)  # no coupon
            payment(db, 5, 400, "0")  # zero coupon
            payment(db, 6, 500, "99.00", status="rejected")  # not relevant
        with session_factory() as db:
            assert store.pending_orders(db, 10, NOW) == [200, 100]
            assert store.pending_count(db) == 2
            assert store.pending_orders(db, 1, NOW) == [200]


class TestRun:
    def test_ok_and_404_are_stored_once_with_their_lines(self, session_factory) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "137937.00", minutes=2)
            payment(db, 2, 200, "500.00", minutes=1)
        client = FakeClient(
            {100: response(200, fixture("discounts_top_coupon_1")), 200: response(404, fixture("discounts_not_found"))}
        )
        result = run(session_factory, client)
        assert result.as_detail() == {
            "calls": 2,
            "fetched": 1,
            "none": 1,
            "errors": 0,
            "stopped": None,
            "backoff_until": None,
            "pending_left": 0,
        }
        assert client.paths == ["/orders/100/discounts", "/orders/200/discounts"]
        fetched = {row.order_id: row for row in rows(session_factory, MlOrderDiscounts)}
        assert (fetched[100].status, fetched[100].http_status, fetched[100].attempts) == ("ok", 200, 1)
        assert fetched[100].body == fixture("discounts_top_coupon_1")
        assert (fetched[200].status, fetched[200].http_status) == ("none", 404)
        lines = rows(session_factory, MlOrderDiscountLine)
        assert sorted((line.order_id, line.type) for line in lines) == [(100, "coupon"), (100, "discount")]
        assert run(session_factory, FakeClient({})).calls == 0  # settled: never asked again

    def test_a_404_body_inside_a_200_is_stored_as_none(self, session_factory) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "1.00")
        run(session_factory, FakeClient({100: response(200, fixture("discounts_not_found"))}))
        (row,) = rows(session_factory, MlOrderDiscounts)
        assert (row.status, row.http_status) == ("none", 404)

    def test_errors_are_retried_until_the_attempt_limit(self, session_factory) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "1.00")
        client = FakeClient({100: response(500, {"message": "boom"})})
        for attempt in range(1, store.MAX_ATTEMPTS + 1):
            at = NOW + attempt * store.ERROR_RETRY
            result = ingestion.run(
                session_factory, client, now=lambda: at, deadline=at + timedelta(seconds=20), max_calls=30
            )
            assert result.counts["error"] == 1
            (row,) = rows(session_factory, MlOrderDiscounts)
            assert (row.status, row.attempts) == ("error", attempt)
        far = NOW + 100 * store.ERROR_RETRY
        assert ingestion.run(session_factory, client, now=lambda: far, deadline=far, max_calls=30).calls == 0
        assert len(client.paths) == store.MAX_ATTEMPTS

    def test_an_error_waits_before_it_is_asked_again(self, session_factory) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "1.00")
        client = FakeClient({100: response(503, None)})
        run(session_factory, client)
        assert run(session_factory, client).calls == 0  # 30 s later, as the worker would: not yet
        soon = NOW + store.ERROR_RETRY - timedelta(seconds=1)
        assert ingestion.run(session_factory, client, now=lambda: soon, deadline=soon, max_calls=30).calls == 0
        later = NOW + store.ERROR_RETRY
        assert (
            ingestion.run(
                session_factory, client, now=lambda: later, deadline=later + timedelta(seconds=20), max_calls=30
            ).calls
            == 1
        )

    def test_a_body_that_cannot_be_stored_counts_an_error_and_the_run_goes_on(self, session_factory) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "1.00", minutes=2)
            payment(db, 2, 200, "1.00", minutes=1)
        body = copy.deepcopy(fixture("discounts_top_coupon_1"))  # perturbed copy: a NUL Postgres JSONB refuses
        body["details"][0]["items"][0]["id"] = "MLA\u0000"
        client = FakeClient({100: response(200, body), 200: response(200, fixture("discounts_top_coupon_2"))})
        result = run(session_factory, client)
        assert (result.calls, result.counts["error"], result.counts["ok"]) == (2, 1, 1)
        fetched = {row.order_id: row for row in rows(session_factory, MlOrderDiscounts)}
        assert (fetched[100].status, fetched[100].attempts, fetched[100].body) == ("error", 1, None)
        assert fetched[200].status == "ok"

    def test_an_ok_after_an_error_settles_the_order(self, session_factory) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "1.00")
        run(session_factory, FakeClient({100: response(500, None)}))
        later = NOW + store.ERROR_RETRY
        ok = FakeClient({100: response(200, fixture("discounts_top_coupon_2"))})
        ingestion.run(session_factory, ok, now=lambda: later, deadline=later + timedelta(seconds=20), max_calls=30)
        (row,) = rows(session_factory, MlOrderDiscounts)
        assert (row.status, row.attempts) == ("ok", 2)
        assert len(rows(session_factory, MlOrderDiscountLine)) == 3

    def test_a_429_stops_the_run_and_backs_off_growing_per_consecutive_run(self, session_factory) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "1.00", minutes=2)
            payment(db, 2, 200, "1.00", minutes=1)
        limited = FakeClient({100: response(429, None), 200: response(200, fixture("discounts_top_coupon_1"))})
        first = run(session_factory, limited)
        assert (first.stopped, first.calls, first.backoff_until) == ("rate_limited", 1, NOW + timedelta(seconds=60))
        assert rows(session_factory, MlOrderDiscounts) == []
        backing_off = run(session_factory, limited)
        assert (backing_off.stopped, backing_off.calls, backing_off.pending_left) == ("backoff", 0, 2)
        later = lambda: NOW + timedelta(seconds=61)  # noqa: E731
        second = ingestion.run(session_factory, limited, now=later, deadline=NOW + timedelta(minutes=5), max_calls=30)
        assert second.backoff_until == later() + timedelta(seconds=120)
        (state,) = rows(session_factory, MlOrderDiscountsState)
        assert state.consecutive_429 == 2

    def test_retry_after_lengthens_the_back_off_and_an_answer_clears_it(self, session_factory) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "1.00")
        run(session_factory, FakeClient({100: response(429, None, headers={"retry-after": "300"})}))
        (state,) = rows(session_factory, MlOrderDiscountsState)
        assert state.backoff_until == NOW + timedelta(seconds=300)
        later = lambda: NOW + timedelta(seconds=301)  # noqa: E731
        ok = FakeClient({100: response(200, fixture("discounts_top_coupon_1"))})
        assert (
            ingestion.run(session_factory, ok, now=later, deadline=NOW + timedelta(minutes=9), max_calls=30).calls == 1
        )
        (state,) = rows(session_factory, MlOrderDiscountsState)
        assert (state.consecutive_429, state.backoff_until) == (0, None)

    def test_a_429_after_answers_in_the_same_run_still_grows_the_back_off(self, session_factory) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "1.00", minutes=2)
            payment(db, 2, 200, "1.00", minutes=1)
            db.add(
                MlOrderDiscountsState(id=store.STATE_ID, consecutive_429=1, backoff_until=NOW - timedelta(seconds=1))
            )
        client = FakeClient({100: response(200, fixture("discounts_top_coupon_1")), 200: response(429, None)})
        result = run(session_factory, client)
        assert result.backoff_until == NOW + timedelta(seconds=120)
        (state,) = rows(session_factory, MlOrderDiscountsState)
        assert state.consecutive_429 == 2

    def test_a_429_body_inside_a_200_also_backs_off(self, session_factory) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "1.00")
        body = copy.deepcopy(fixture("discounts_not_found"))  # perturbed copy of a real error body
        body.update(status=429, error="too_many_requests")
        result = run(session_factory, FakeClient({100: response(200, body)}))
        assert result.stopped == "rate_limited" and rows(session_factory, MlOrderDiscounts) == []

    @pytest.mark.parametrize(
        ("answer", "stopped"),
        [
            (response(401, None), "blocked"),
            (response(0, None, error=OUTCOME_NO_TOKEN), "blocked"),
            (response(0, None, error="ConnectError"), "transport"),
            (response(0, None, error=DEADLINE), DEADLINE),
        ],
    )
    def test_blocked_transport_and_deadline_stop_without_counting_against_the_order(
        self, session_factory, answer, stopped
    ) -> None:
        with session_factory() as db:
            payment(db, 1, 100, "1.00")
        result = run(session_factory, FakeClient({100: answer}))
        assert result.stopped == stopped and result.pending_left == 1
        assert rows(session_factory, MlOrderDiscounts) == []
        assert rows(session_factory, MlOrderDiscountsState) == []

    def test_max_calls_caps_the_run(self, session_factory) -> None:
        with session_factory() as db:
            for n in range(3):
                payment(db, n + 1, 100 + n, "1.00", minutes=n)
        answers = {100 + n: response(404, fixture("discounts_not_found")) for n in range(3)}
        result = run(session_factory, FakeClient(answers), max_calls=2)
        assert (result.calls, result.pending_left) == (2, 1)


class TestBackoffSeconds:
    def test_doubles_per_run_and_caps_at_an_hour(self) -> None:
        assert [store.backoff_seconds(n) for n in (1, 2, 3, 7, 20)] == [60, 120, 240, 3600, 3600]

    def test_a_retry_after_longer_than_the_cap_is_honored_up_to_a_day(self) -> None:
        assert store.backoff_seconds(1, 7200) == 7200
        assert store.backoff_seconds(1, 10**9) == 86400
