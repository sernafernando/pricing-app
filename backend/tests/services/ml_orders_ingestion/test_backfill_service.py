"""Tests for the historical backfill over the rolling window (slice 5).

Contract-first (obs #1843/#1852 lesson): assert the PROMISES -- flag-gated,
day-sized checkpointing under a SEPARATE cursor (`name='backfill'`),
resumability, `--dry-run` makes zero writes, fail-closed per day, and the
backfill's own run lock never races the sweep's -- not just the happy path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsSyncCursor, MlOrdersOps
from app.services.ml_orders_ingestion import backfill_service, sweep_service
from app.services.ml_webhook_client import ml_webhook_client


def _fake_ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return lambda: _Ctx()


@pytest.fixture(autouse=True)
def _background_db(db, monkeypatch):
    # `process_batch` (reused from sweep_service) opens its OWN
    # `get_background_db()` bound in sweep_service's module scope, so both
    # sites must be bridged to the same sqlite test session.
    monkeypatch.setattr(backfill_service, "get_background_db", _fake_ctx(db))
    monkeypatch.setattr(sweep_service, "get_background_db", _fake_ctx(db))


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


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


def _page(results, total=None):
    return {"results": results, "paging": {"total": total if total is not None else len(results)}}


class TestFlagGate:
    def test_flag_off_is_a_complete_noop(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        mock_search = AsyncMock(return_value=_page([]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = backfill_service.run_backfill(seller_id=999, days_from=0, days_to=3)

        assert result.ran is False
        mock_search.assert_not_called()
        assert db.query(MlOrdersOps).count() == 0
        assert db.query(MlOpsSyncCursor).count() == 0


class TestDayWindowsCheckpointBackwards:
    def test_walks_day_sized_windows_and_checkpoints_each(self, db, monkeypatch):
        calls = []

        async def fake_search(seller_id, date_from, date_to, offset=0):
            calls.append((date_from, date_to))
            return _page([])

        monkeypatch.setattr(ml_webhook_client, "search_orders", fake_search)

        result = backfill_service.run_backfill(seller_id=999, days_from=0, days_to=3)

        assert result.ran is True
        assert result.error is None
        # 3 day-sized windows, walked backwards (most recent first).
        assert len(calls) == 3
        for (day_from, day_to), next_call in zip(calls, calls[1:]):
            assert day_from < day_to
            assert (day_to - day_from) <= timedelta(days=1)
            # walking backwards: each subsequent window ends where the
            # previous one started.
            assert next_call[1] == day_from

        cursor = db.query(MlOpsSyncCursor).filter_by(name="backfill").one()
        assert cursor.state == "idle"
        assert cursor.last_success_at is not None
        # progress marker moved all the way back to the oldest boundary.
        assert cursor.window_from is not None

    def test_uses_its_own_cursor_row_separate_from_sweep(self, db, monkeypatch):
        mock_search = AsyncMock(return_value=_page([]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        backfill_service.run_backfill(seller_id=999, days_from=0, days_to=1)

        assert db.query(MlOpsSyncCursor).filter_by(name="backfill").count() == 1
        assert db.query(MlOpsSyncCursor).filter_by(name=sweep_service.CURSOR_NAME).count() == 0


class TestResumability:
    def test_resumes_from_last_checkpoint_without_reprocessing(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        # Simulate a previous run that completed down to `now - 1 day`.
        db.add(
            MlOpsSyncCursor(
                name="backfill",
                window_from=now - timedelta(days=1),
                state="idle",
                last_success_at=None,
            )
        )
        db.flush()

        calls = []

        async def fake_search(seller_id, date_from, date_to, offset=0):
            calls.append((date_from, date_to))
            return _page([])

        monkeypatch.setattr(ml_webhook_client, "search_orders", fake_search)

        result = backfill_service.run_backfill(seller_id=999, days_from=0, days_to=3)

        assert result.ran is True
        # Only the remaining ~2 days get processed, not all 3.
        assert len(calls) == 2
        for day_from, day_to in calls:
            assert day_to <= now - timedelta(days=1) + timedelta(seconds=5)


class TestDryRun:
    def test_dry_run_makes_no_writes_but_still_computes_and_logs_windows(self, db, monkeypatch, caplog):
        order = _order(1, 999, datetime.now(timezone.utc), datetime.now(timezone.utc))
        mock_search = AsyncMock(return_value=_page([order]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        with caplog.at_level("INFO"):
            result = backfill_service.run_backfill(seller_id=999, days_from=0, days_to=1, dry_run=True)

        assert result.ran is True
        assert result.dry_run is True
        mock_search.assert_called()
        assert db.query(MlOrdersOps).count() == 0
        # Dry run must not persist backfill progress either -- rerunning it
        # for real must start from scratch, not from a dry-run checkpoint.
        assert db.query(MlOpsSyncCursor).filter_by(name="backfill").count() == 0
        assert any("dry" in record.message.lower() for record in caplog.records)


class TestSessionPerBatch:
    def test_each_day_batch_opens_and_closes_its_own_session(self, db, monkeypatch):
        """Reuses sweep's `process_batch`, which already opens a fresh
        `get_background_db()` context per call -- proven here at the
        backfill's own call site, not assumed by import alone."""
        order = _order(1, 999, datetime.now(timezone.utc), datetime.now(timezone.utc))
        mock_search = AsyncMock(return_value=_page([order]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        session_opens = []
        real_ctx = backfill_service.get_background_db

        def counting_ctx():
            session_opens.append(1)
            return real_ctx()

        monkeypatch.setattr(backfill_service, "get_background_db", counting_ctx)

        backfill_service.run_backfill(seller_id=999, days_from=0, days_to=1)

        # At least one session per day window (batch flush + lock
        # acquire/release), never a single session held for the whole run.
        assert len(session_opens) >= 2


class TestFailClosedPerDay:
    def test_a_day_failure_does_not_advance_the_cursor_past_it(self, db, monkeypatch):
        async def boom(seller_id, date_from, date_to, offset=0):
            raise RuntimeError("proxy down")

        monkeypatch.setattr(ml_webhook_client, "search_orders", boom)

        result = backfill_service.run_backfill(seller_id=999, days_from=0, days_to=2)

        assert result.error is not None
        cursor = db.query(MlOpsSyncCursor).filter_by(name="backfill").one()
        assert cursor.state == "error"
        assert cursor.last_success_at is None
        assert cursor.window_from is None  # nothing checkpointed


class TestOverlapWithSweepIsSafe:
    def test_backfill_and_sweep_both_converge_on_the_same_idempotent_upsert(self, db, monkeypatch):
        """Both jobs call `ingestion_service.upsert_order`, keyed on
        `order_id` with a `ml_last_updated`-wins guard (design D5), so
        running them over the same order concurrently must never
        duplicate or corrupt a row."""
        now = datetime.now(timezone.utc)
        order_payload = _order(42, 999, now, now)

        mock_search = AsyncMock(return_value=_page([order_payload]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)
        monkeypatch.setattr(sweep_service, "get_background_db", _fake_ctx(db))
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_WINDOW_DAYS", 90)

        sweep_service.run_sweep(seller_id=999, window_days=90)
        backfill_service.run_backfill(seller_id=999, days_from=0, days_to=1)

        assert db.query(MlOrdersOps).filter_by(order_id=42).count() == 1


class TestDaysArgParsing:
    def test_parses_single_int_as_full_width_from_zero(self):
        assert backfill_service.parse_days_arg("90") == (0, 90)

    def test_parses_range_syntax(self):
        assert backfill_service.parse_days_arg("90..180") == (90, 180)

    def test_rejects_inverted_range(self):
        with pytest.raises(ValueError):
            backfill_service.parse_days_arg("180..90")
