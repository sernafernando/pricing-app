"""Tests for the ML orders reconciliation sweep (slice 3).

Contract-first (obs #1843 lesson): assert the PROMISES (flag-gated,
fail-closed window semantics, cursor NOT advanced on an unresolved
failure, out-of-window hard exclusion + instrumentation) not just the
happy-path behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsDivergence, MlOpsSyncCursor, MlOrdersOps
from app.services.ml_orders_ingestion import sweep_service
from app.services.ml_webhook_client import ml_webhook_client


def _fake_ctx(db):
    """Bridges `sweep_service.get_background_db()` (bound to the real,
    unreachable-in-tests Postgres engine) to the sqlite `db` fixture, the
    same pattern used by `tests/unit/test_drain_promo_refresh.py` for the
    same reason: the test DB is sqlite (conftest `TEST_DB_URL="sqlite://"`)
    and every session `sweep_service` opens must land in that one
    transactional session so assertions can see the writes."""

    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return lambda: _Ctx()


@pytest.fixture(autouse=True)
def _background_db(db, monkeypatch):
    monkeypatch.setattr(sweep_service, "get_background_db", _fake_ctx(db))


def _order(order_id: int, seller_id: int, when: datetime, created: datetime) -> dict:
    return {
        "id": order_id,
        "status": "paid",
        "date_created": created.isoformat(),
        "date_last_updated": when.isoformat(),
        "seller": {"id": seller_id},
        "buyer": {"id": 1, "nickname": "x"},
        "order_items": [],
    }


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_WINDOW_DAYS", 90)


def _page(results, total=None):
    return {"results": results, "paging": {"total": total if total is not None else len(results)}}


class TestFlagGate:
    def test_flag_off_is_a_complete_noop(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        mock_search = AsyncMock(return_value=_page([]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is False
        mock_search.assert_not_called()
        assert db.query(MlOrdersOps).count() == 0
        assert db.query(MlOpsSyncCursor).count() == 0


class TestCursorAdvance:
    def test_success_advances_cursor(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        mock_search = AsyncMock(return_value=_page([_order(1, 999, recent, recent)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is True
        assert result.error is None
        cursor = db.query(MlOpsSyncCursor).filter_by(name="sweep").one()
        assert cursor.state == "idle"
        assert cursor.last_success_at is not None
        assert cursor.window_to is not None

    def test_window_failure_does_not_advance_cursor(self, db, monkeypatch):
        mock_search = AsyncMock(return_value=None)  # proxy down / 5xx / timeout
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is True
        assert result.error is not None
        cursor = db.query(MlOpsSyncCursor).filter_by(name="sweep").one()
        assert cursor.state == "error"
        assert cursor.last_success_at is None
        assert cursor.window_to is None  # window NOT checkpointed

    def test_retried_after_failure_uses_same_starting_point(self, db, monkeypatch):
        """The unresolved-failure guarantee, made concrete: after a failed
        pass the NEXT pass must retry from (essentially) the same window
        start, not silently skip forward past the gap."""
        mock_search = AsyncMock(return_value=None)
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)
        sweep_service.run_sweep(seller_id=999, window_days=90)
        first_call_args = mock_search.call_args

        mock_search.reset_mock(return_value=True)
        mock_search.return_value = None
        sweep_service.run_sweep(seller_id=999, window_days=90)
        second_call_args = mock_search.call_args

        # date_from passed to search_orders must not have advanced past the
        # still-unconfirmed window -- both calls recompute
        # `window_from_floor` from a fresh `now()`, so allow for the sub-
        # second wall-clock drift between the two calls, but the gap must
        # be nowhere near the 90-day window itself.
        first_date_from = first_call_args.args[1]
        second_date_from = second_call_args.args[1]
        assert abs((second_date_from - first_date_from).total_seconds()) < 5


class TestWindowBisection:
    def test_bisects_window_when_total_exceeds_cap(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        calls = []

        async def fake_search(seller_id, date_from, date_to, offset=0):
            calls.append((date_from, date_to, offset))
            span = date_to - date_from
            # First call sees a window too wide -> report over-cap; once
            # bisected below ~ half a day, report a normal small result.
            if span > timedelta(hours=12):
                return {"results": [], "paging": {"total": 2000}}
            return _page([_order(len(calls), 999, recent, recent)])

        monkeypatch.setattr(ml_webhook_client, "search_orders", fake_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is True
        assert result.error is None
        # More than one call proves bisection actually happened (not a
        # single offset-deepening call).
        assert len(calls) > 1
        assert result.orders_upserted >= 1


class TestOutOfWindowCounter:
    def test_order_outside_window_is_counted_not_ingested(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent_update = now - timedelta(days=1)
        old_created = now - timedelta(days=400)  # older than the 90-day window
        mock_search = AsyncMock(return_value=_page([_order(42, 999, recent_update, old_created)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is True
        assert result.orders_out_of_window == 1
        assert db.query(MlOrdersOps).filter_by(order_id=42).count() == 0
        divergence = db.query(MlOpsDivergence).filter_by(order_id=42, kind="out_of_window_update").one()
        assert divergence.field is None

    def test_repeat_detection_updates_not_duplicates(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent_update = now - timedelta(days=1)
        old_created = now - timedelta(days=400)
        mock_search = AsyncMock(return_value=_page([_order(42, 999, recent_update, old_created)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        sweep_service.run_sweep(seller_id=999, window_days=90)
        sweep_service.run_sweep(seller_id=999, window_days=90)

        assert db.query(MlOpsDivergence).filter_by(order_id=42, kind="out_of_window_update").count() == 1

    def test_order_inside_window_is_ingested_normally(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        mock_search = AsyncMock(return_value=_page([_order(7, 999, recent, recent)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.orders_out_of_window == 0
        assert result.orders_upserted == 1
        assert db.query(MlOrdersOps).filter_by(order_id=7).count() == 1
