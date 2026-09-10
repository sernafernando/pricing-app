"""Tests for the event-driven activity drain
(ml-activity-receiver, slice 3 of 4).

Contract-first (same discipline as `test_sweep_service.py` /
`test_backfill_payments_costs_service.py`): assert the PROMISES this
slice exists to prove --
  1. `activity_cursor` advances only after `process_batch`'s write
     session has committed.
  2. A truncated page walk is not stamped complete.
  3. HTTP 400 (`ActivityCursorRejected`) is visible (error state), never
     a silent reset of the cursor.
  4. `orders_unresolved` (genuinely failed) stays distinct from
     `orders_not_attempted` (the budget never reached it) -- the same
     bug class fixed in commit `9cc60ef7`.
Plus: flag-off is a complete no-op with `error=None`, and re-processing
an already-ingested order (cursor moved twice over the same order) is a
true no-op.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsDivergence, MlOpsSyncCursor, MlOrdersOps
from app.services.ml_orders_ingestion import activity_receiver_service as service
from app.services.ml_orders_ingestion import sweep_service
from app.services.ml_webhook_client import ActivityCursorRejected, ml_webhook_client


def _fake_ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return lambda: _Ctx()


@pytest.fixture(autouse=True)
def _background_db(db, monkeypatch):
    # `process_batch` is reused straight from `sweep_service`, which opens
    # ITS OWN `get_background_db()` -- both module bindings must land in
    # the same sqlite test session, same discipline as the backfill's own
    # test module.
    monkeypatch.setattr(service, "get_background_db", _fake_ctx(db))
    monkeypatch.setattr(sweep_service, "get_background_db", _fake_ctx(db))


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_WINDOW_DAYS", 90)


@pytest.fixture(autouse=True)
def _no_real_cost_fetch(monkeypatch):
    """`process_batch` calls into shipment/cost/payment sync for any
    order carrying a `shipping_id` -- none of the orders built by
    `_order()` below carry one, so this is a defensive net (matches
    `test_sweep_service.py`'s own default) rather than something these
    tests rely on."""
    monkeypatch.setattr(ml_webhook_client, "get_shipment_costs", AsyncMock(return_value=None))
    monkeypatch.setattr(ml_webhook_client, "get_shipment", AsyncMock(return_value=None))
    monkeypatch.setattr(ml_webhook_client, "get_payment", AsyncMock(return_value=None))


def _order(order_id: int, seller_id: int = 999, when: datetime = None, created: datetime = None) -> dict:
    """The shape `/orders/<id>` ACTUALLY returns, which is what the drain
    calls -- note `last_updated`, NOT `date_last_updated`.

    This fixture used to invent `date_last_updated`, the shape of
    `/orders/search` (what the sweep calls). That single wrong key made
    every test here pass against a payload ML never sends, while in
    production every resolved order failed to map and nothing was
    ingested for a week. Verified live on 2026-09-10 against order
    2000018378699734: the single-order endpoint has no
    `date_last_updated` key at all.
    """
    when = when or (datetime.now(timezone.utc) - timedelta(days=1))
    created = created or when
    return {
        "id": order_id,
        "status": "paid",
        "date_created": created.isoformat(),
        "last_updated": when.isoformat(),
        "seller": {"id": seller_id},
        "buyer": {"id": 1, "nickname": "x"},
        "order_items": [],
    }


def _event(order_id: int, topic: str = "orders_v2") -> dict:
    return {
        "topic": topic,
        "order_id": order_id,
        "pack_id": None,
        "resource": f"/orders/{order_id}",
        "sent": datetime.now(timezone.utc).isoformat(),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }


def _page(events, has_more=False, next_cursor="cursor-2"):
    return {"events": events, "has_more": has_more, "next_cursor": next_cursor}


class TestFlagGate:
    def test_flag_off_is_a_complete_noop(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        mock_activity = AsyncMock(return_value=_page([]))
        mock_get_order = AsyncMock(return_value=_order(1))
        monkeypatch.setattr(ml_webhook_client, "get_activity", mock_activity)
        monkeypatch.setattr(ml_webhook_client, "get_order", mock_get_order)

        result = service.drain_activity()

        assert result.ran is False
        assert result.error is None
        mock_activity.assert_not_called()
        mock_get_order.assert_not_called()
        assert db.query(MlOrdersOps).count() == 0
        assert db.query(MlOpsSyncCursor).count() == 0

    def test_flag_off_mutation_verified(self, db, monkeypatch):
        """Mutation-verify the guard actually gates the HTTP/DB work: with
        the flag forced back on (simulating the guard being broken/
        bypassed), the exact same setup DOES call `get_activity` -- proving
        the `assert_not_called()` above is a real check, not a tautology
        that would pass even if the guard did nothing."""
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        mock_activity = AsyncMock(return_value=_page([]))
        monkeypatch.setattr(ml_webhook_client, "get_activity", mock_activity)
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=None))

        # With the flag forced True (the mutated/bypassed-guard scenario),
        # the drain DOES proceed and DOES call get_activity.
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        service.drain_activity()
        mock_activity.assert_called_once()

        # Restored to the real, tested state: flag off never calls it.
        mock_activity.reset_mock()
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        # Fresh lock (the prior run above claimed and released it).
        result = service.drain_activity()
        assert result.ran is False
        mock_activity.assert_not_called()


class TestCursorAdvancesOnlyAfterCommit:
    def test_success_advances_cursor(self, db, monkeypatch):
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(1)], has_more=False, next_cursor="c1")),
        )
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_order(1)))

        result = service.drain_activity()

        assert result.ran is True
        assert result.error is None
        assert db.query(MlOrdersOps).filter_by(order_id=1).count() == 1
        cursor = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        assert cursor.state == "idle"
        assert cursor.activity_cursor == "c1"

    def test_ingestion_failure_mid_page_does_not_advance_cursor(self, db, monkeypatch):
        """Mutation: force `process_batch` to raise mid-page (simulating a
        write failure) and confirm `activity_cursor` did NOT move -- the
        same events must be re-delivered next run."""
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(1)], has_more=False, next_cursor="c1")),
        )
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_order(1)))
        monkeypatch.setattr(service, "process_batch", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))

        result = service.drain_activity()

        assert result.ran is True
        assert result.error is not None
        cursor = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        assert cursor.state == "error"
        assert cursor.activity_cursor is None  # never advanced
        assert db.query(MlOrdersOps).count() == 0


class TestTruncatedPageNotStampedComplete:
    def test_order_budget_exhausted_mid_page_leaves_pass_incomplete(self, db, monkeypatch):
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(1), _event(2)], has_more=True, next_cursor="c1")),
        )
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_order(1)))
        monkeypatch.setattr(service, "MAX_ACTIVITY_ORDER_FETCHES_PER_PASS", 1)

        result = service.drain_activity()

        assert result.ran is True
        assert result.orders_resolved == 1
        assert result.orders_not_attempted == 1
        assert result.budget_exhausted is True

        cursor = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        assert cursor.state == "idle"
        assert cursor.last_success_at is None  # NOT stamped complete
        assert cursor.activity_cursor is None  # this page never advanced past

    def test_mutation_hardcoding_complete_true_would_fail(self, db, monkeypatch):
        """Mutation-verify: temporarily force `release_lock_as_idle` to
        always be called with `complete=True` and confirm the assertion
        above would fail (proving it is a real check, not a tautology)."""
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(1), _event(2)], has_more=True, next_cursor="c1")),
        )
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_order(1)))
        monkeypatch.setattr(service, "MAX_ACTIVITY_ORDER_FETCHES_PER_PASS", 1)

        original_release = service.release_lock_as_idle

        def _forced_complete(now, complete=True, cursor_name=service.CURSOR_NAME):
            return original_release(now, complete=True, cursor_name=cursor_name)

        monkeypatch.setattr(service, "release_lock_as_idle", _forced_complete)

        service.drain_activity()

        cursor = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        # With the mutation, last_success_at WOULD be set -- proving the
        # real code path (asserted in the test above) actually depends on
        # `complete=False` being passed for real.
        assert cursor.last_success_at is not None


class TestInvalidCursorIsVisibleNeverSilentReset:
    def test_http_400_marks_error_state_and_leaves_cursor_untouched(self, db, monkeypatch):
        cursor = MlOpsSyncCursor(name="ml_activity", state="idle", activity_cursor="known-good")
        db.add(cursor)
        db.flush()

        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(side_effect=ActivityCursorRejected("cursor invalido")),
        )
        get_order_mock = AsyncMock(return_value=_order(1))
        monkeypatch.setattr(ml_webhook_client, "get_order", get_order_mock)

        result = service.drain_activity()

        assert result.ran is True
        assert result.error is not None

        cursor = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        assert cursor.state == "error"
        assert cursor.activity_cursor == "known-good"  # byte-identical, never reset
        get_order_mock.assert_not_called()


class TestUnresolvedVsNotAttemptedDistinction:
    def test_budget_exhaustion_keeps_the_two_counters_distinct(self, db, monkeypatch):
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(1), _event(2), _event(3)], has_more=True, next_cursor="c1")),
        )

        def _get_order(order_id):
            if order_id == 1:
                return _order(1)
            return None  # order 2 genuinely fails to resolve

        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(side_effect=_get_order))
        monkeypatch.setattr(service, "MAX_ACTIVITY_ORDER_FETCHES_PER_PASS", 2)

        result = service.drain_activity()

        assert result.orders_resolved == 1
        assert result.orders_unresolved == 1  # order 2: attempted, ML said no
        assert result.orders_not_attempted == 1  # order 3: budget never reached it


class TestDedupPerPassNotPerPage:
    def test_same_order_id_across_two_pages_fetched_once(self, db, monkeypatch):
        page1 = _page([_event(1), _event(1)], has_more=True, next_cursor="c1")
        page2 = _page([_event(1)], has_more=False, next_cursor="c2")
        monkeypatch.setattr(ml_webhook_client, "get_activity", AsyncMock(side_effect=[page1, page2]))
        get_order_mock = AsyncMock(return_value=_order(1))
        monkeypatch.setattr(ml_webhook_client, "get_order", get_order_mock)

        result = service.drain_activity()

        assert result.ran is True
        assert result.error is None
        get_order_mock.assert_called_once_with(1)
        assert result.orders_resolved == 1


class TestIdempotentReDelivery:
    def test_reprocessing_same_order_is_a_noop(self, db, monkeypatch):
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(1)], has_more=False, next_cursor="c1")),
        )
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_order(1)))

        first = service.drain_activity()
        assert first.ran is True
        assert db.query(MlOrdersOps).filter_by(order_id=1).count() == 1

        # A second drain "delivers" the same event again (e.g. the cursor
        # advance committed but the ping caller retried) with an
        # unchanged payload.
        cursor = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        cursor.state = "idle"
        db.flush()

        second = service.drain_activity()

        assert second.ran is True
        assert second.error is None
        assert db.query(MlOrdersOps).filter_by(order_id=1).count() == 1  # no duplicate row


class TestConcurrentPing:
    def test_second_drain_while_locked_is_a_noop(self, db, monkeypatch):
        cursor = MlOpsSyncCursor(name="ml_activity", state="running", detail=datetime.now(timezone.utc).isoformat())
        db.add(cursor)
        db.flush()

        mock_activity = AsyncMock(return_value=_page([]))
        monkeypatch.setattr(ml_webhook_client, "get_activity", mock_activity)

        result = service.drain_activity()

        assert result.ran is False
        assert result.error == "already running"
        mock_activity.assert_not_called()


class TestUnusableNextCursorIsNeverPersisted:
    """A page whose `next_cursor` is missing or null must not reach
    `activity_cursor`. Persisting NULL there IS the silent reset back to
    "never drained" that this module promises is impossible -- the next
    run would re-drain the entire feed from zero. With `has_more` still
    true it is also an infinite walk: `since` returns to the start, the
    per-pass dedup suppresses every `get_order`, and the loop spins
    against the bridge until the pass deadline."""

    # Capped on purpose, everywhere in this class. Without the guard the
    # drain genuinely spins -- `since` goes back to the start, the
    # per-pass dedup suppresses every `get_order`, and nothing consumes
    # budget -- so it would only stop at `PASS_TIME_BUDGET`, roughly 25
    # minutes. A regression has to fail these tests in seconds instead of
    # hanging CI, so the mock runs out of pages and raises.
    _MAX_PAGES_BEFORE_GIVING_UP = 3

    def _drain_with_cursor(self, db, monkeypatch, next_cursor, has_more):
        cursor = MlOpsSyncCursor(name="ml_activity", state="idle", activity_cursor="known-good")
        db.add(cursor)
        db.flush()
        page = _page([_event(1)], has_more=has_more, next_cursor=next_cursor)
        activity = AsyncMock(
            side_effect=[page] * self._MAX_PAGES_BEFORE_GIVING_UP + [RuntimeError("walked past an unusable cursor")]
        )
        monkeypatch.setattr(ml_webhook_client, "get_activity", activity)
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_order(1)))
        return service.drain_activity(), activity

    @pytest.mark.parametrize("next_cursor", [None, ""])
    def test_the_stored_cursor_is_left_untouched(self, db, monkeypatch, next_cursor):
        self._drain_with_cursor(db, monkeypatch, next_cursor, has_more=True)

        stored = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        assert stored.activity_cursor == "known-good"

    def test_the_pass_is_not_stamped_complete(self, db, monkeypatch):
        self._drain_with_cursor(db, monkeypatch, None, has_more=True)

        stored = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        assert stored.last_success_at is None

    def test_it_stops_instead_of_walking_forever(self, db, monkeypatch):
        """`has_more=True` with no usable cursor is the infinite-loop
        shape: the bridge must be asked exactly once, not repeatedly.

        The mock is capped on purpose. Without the guard the drain really
        does spin -- `since` returns to the start, the per-pass dedup
        suppresses every `get_order`, and nothing consumes budget -- so it
        would only stop at `PASS_TIME_BUDGET`, roughly 25 minutes. A
        regression must fail this test in seconds, not hang CI, so the
        fourth call raises instead of returning another page.
        """
        _, activity = self._drain_with_cursor(db, monkeypatch, None, has_more=True)

        assert activity.await_count == 1


class TestAnUnresolvedOrderLeavesVisibleDebt:
    """`get_order` returning None covers timeouts, network errors and 5xx
    -- transient answers, not ML's final word. Once the cursor moves past
    that page the event never comes back, so the miss must survive as an
    operator-facing row instead of a number that dies with the request.

    The cursor still advances on purpose: refusing to advance while any
    order is unresolved wedges the whole feed behind a single permanently
    dead order, which is the bug fixed in `9cc60ef7` for the payments
    backfill. The debt is recorded and the audit sweep re-ingests it.
    """

    def _unresolved_rows(self, db):
        return db.query(MlOpsDivergence).filter(MlOpsDivergence.field == service.UNRESOLVED_FIELD).all()

    def test_a_miss_is_recorded_against_its_own_order(self, db, monkeypatch):
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(1), _event(2)], has_more=False, next_cursor="c1")),
        )

        def _get_order(order_id):
            return _order(1) if order_id == 1 else None

        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(side_effect=_get_order))

        service.drain_activity()

        rows = self._unresolved_rows(db)
        assert [r.order_id for r in rows] == [2]

    def test_the_cursor_still_advances_so_one_dead_order_cannot_wedge_the_feed(self, db, monkeypatch):
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(2)], has_more=False, next_cursor="c1")),
        )
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=None))

        service.drain_activity()

        stored = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        assert stored.activity_cursor == "c1"

    def test_resolving_later_clears_the_debt(self, db, monkeypatch):
        """A settled debt must not linger as a permanent false alarm --
        the same lesson as clearing the cost-sync give-up counter on
        success."""
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(2)], has_more=False, next_cursor="c1")),
        )
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=None))
        service.drain_activity()
        assert len(self._unresolved_rows(db)) == 1

        # Second pass: the same order now resolves.
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(2)], has_more=False, next_cursor="c2")),
        )
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_order(2)))
        service.drain_activity()

        assert self._unresolved_rows(db) == []


class TestColdStart:
    """The very first run has `activity_cursor = NULL`. Verified live
    against the bridge on 2026-09-09: `?since=` (empty) answers HTTP 200
    and starts from the beginning of the feed, so a cold start is a
    normal drain, not an `ActivityCursorRejected` that would park the
    receiver in `state='error'` before it ever ran."""

    def test_a_null_cursor_drains_normally_and_stores_the_first_cursor(self, db, monkeypatch):
        activity = AsyncMock(return_value=_page([_event(1)], has_more=False, next_cursor="first"))
        monkeypatch.setattr(ml_webhook_client, "get_activity", activity)
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_order(1)))

        result = service.drain_activity()

        assert result.error is None
        assert activity.await_args.kwargs["since"] is None
        stored = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        assert stored.activity_cursor == "first"


class TestAResolvedOrderIsActuallyWritten:
    """The drain used to count `orders_resolved` -- ML answered -- and
    throw away what `process_batch` did next. A field-name mismatch made
    every resolved order fail to map, and the pass still reported
    "resolved=N" with nothing ingested. Resolution is the HTTP half; the
    result has to carry the writing half too."""

    def test_an_order_off_the_real_endpoint_is_upserted(self, db, monkeypatch):
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(1)], has_more=False, next_cursor="c1")),
        )
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=_order(1)))

        result = service.drain_activity()

        assert result.orders_resolved == 1
        assert result.orders_upserted == 1
        assert result.orders_mapping_error == 0
        assert db.query(MlOrdersOps).filter_by(order_id=1).one_or_none() is not None

    def test_a_payload_that_cannot_map_is_counted_not_swallowed(self, db, monkeypatch):
        """The failure that actually happened: resolved, then dropped. It
        must show up as a mapping error rather than vanishing."""
        broken = _order(1)
        del broken["last_updated"]
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(1)], has_more=False, next_cursor="c1")),
        )
        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(return_value=broken))

        result = service.drain_activity()

        assert result.orders_resolved == 1
        assert result.orders_upserted == 0
        assert result.orders_mapping_error == 1
        assert db.query(MlOrdersOps).filter_by(order_id=1).one_or_none() is None
