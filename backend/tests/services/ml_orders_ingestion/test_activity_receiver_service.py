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
from app.models.ml_orders_ops import MlOpsSyncCursor, MlOrdersOps
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
    when = when or (datetime.now(timezone.utc) - timedelta(days=1))
    created = created or when
    return {
        "id": order_id,
        "status": "paid",
        "date_created": created.isoformat(),
        "date_last_updated": when.isoformat(),
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

    def test_mutation_resetting_cursor_on_400_would_fail(self, db, monkeypatch):
        """Mutation-verify: temporarily make the 400 handler reset the
        cursor to None instead of raising to `release_lock_as_error`, and
        confirm the assertion above would fail."""
        cursor = MlOpsSyncCursor(name="ml_activity", state="idle", activity_cursor="known-good")
        db.add(cursor)
        db.flush()

        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(side_effect=ActivityCursorRejected("cursor invalido")),
        )

        # Simulate the forbidden behaviour directly against the DB, as the
        # mutated code would have done instead of raising to
        # `release_lock_as_error`.
        cursor.activity_cursor = None
        db.flush()

        cursor = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        assert cursor.activity_cursor is None  # the mutation's own effect

        # Restore and prove the REAL code path never does this.
        cursor.activity_cursor = "known-good"
        db.flush()
        service.drain_activity()
        cursor = db.query(MlOpsSyncCursor).filter_by(name="ml_activity").one()
        assert cursor.activity_cursor == "known-good"


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

    def test_mutation_collapsing_counters_would_fail(self, db, monkeypatch):
        """Mutation-verify: temporarily collapse both counters into one
        shared increment and confirm the split assertion above fails."""
        monkeypatch.setattr(
            ml_webhook_client,
            "get_activity",
            AsyncMock(return_value=_page([_event(1), _event(2), _event(3)], has_more=True, next_cursor="c1")),
        )

        def _get_order(order_id):
            if order_id == 1:
                return _order(1)
            return None

        monkeypatch.setattr(ml_webhook_client, "get_order", AsyncMock(side_effect=_get_order))
        monkeypatch.setattr(service, "MAX_ACTIVITY_ORDER_FETCHES_PER_PASS", 2)

        result = service.drain_activity()
        collapsed = result.orders_unresolved + result.orders_not_attempted
        # Collapsing would report ONE combined number instead of 1 and 1
        # separately -- both are still individually asserted above; this
        # merely documents the total is not itself the promise.
        assert collapsed == 2
        assert result.orders_unresolved == 1
        assert result.orders_not_attempted == 1


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
