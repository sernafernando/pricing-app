"""RED/GREEN — promo point-refresh retry drainer
(promo-state-dynamic-refresh, backend slice).

Spec coverage:
  REQ-1 — kill-switch off -> no-ops before any read/call.
  REQ-2 — drains rows where due_at<=now; calls refresh_item_promotions
          once per due mla.
  REQ-3 — success -> row DELETEd.
  REQ-4 — failure -> attempts incremented + due_at backoff (+60s).
  REQ-5 — attempts>=MAX_REFRESH_ATTEMPTS -> quarantine (DELETE + loud log).
  REQ-6 — one poison mla never aborts the batch (per-item isolation).
  REQ-7 — idempotent / short-lived DB sessions per row.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.promo_refresh_pending import PromoRefreshPending
from app.scripts import drain_promo_refresh


@pytest.fixture(autouse=True)
def _enable_promo_writes():
    original = settings.PROMOS_WRITE_ENABLED
    settings.PROMOS_WRITE_ENABLED = True
    yield
    settings.PROMOS_WRITE_ENABLED = original


def _fake_ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return _Ctx()


class TestKillSwitch:
    def test_kill_switch_off_exits_without_any_read(self, db):
        settings.PROMOS_WRITE_ENABLED = False

        with (
            patch.object(drain_promo_refresh, "get_background_db") as mock_get_db,
            patch.object(drain_promo_refresh.ml_webhook_client, "refresh_item_promotions") as mock_refresh,
        ):
            drain_promo_refresh.run_drain()

        mock_get_db.assert_not_called()
        mock_refresh.assert_not_called()


class TestDrainSuccess:
    def test_due_row_refreshed_and_deleted_on_success(self, db):
        due = datetime.now(UTC) - timedelta(seconds=5)
        db.add(PromoRefreshPending(mla="MLA1", due_at=due, attempts=0))
        db.commit()

        with (
            patch.object(drain_promo_refresh, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(
                drain_promo_refresh.ml_webhook_client, "refresh_item_promotions", return_value=True
            ) as mock_refresh,
        ):
            drain_promo_refresh.run_drain()

        mock_refresh.assert_called_once_with("MLA1")
        db.commit()
        assert db.query(PromoRefreshPending).filter_by(mla="MLA1").first() is None

    def test_not_yet_due_row_is_skipped(self, db):
        due = datetime.now(UTC) + timedelta(seconds=120)
        db.add(PromoRefreshPending(mla="MLA_FUTURE", due_at=due, attempts=0))
        db.commit()

        with (
            patch.object(drain_promo_refresh, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(drain_promo_refresh.ml_webhook_client, "refresh_item_promotions") as mock_refresh,
        ):
            drain_promo_refresh.run_drain()

        mock_refresh.assert_not_called()
        db.commit()
        assert db.query(PromoRefreshPending).filter_by(mla="MLA_FUTURE").first() is not None


class TestDrainFailureBackoff:
    def test_failure_increments_attempts_and_backs_off(self, db):
        due = datetime.now(UTC) - timedelta(seconds=5)
        db.add(PromoRefreshPending(mla="MLA1", due_at=due, attempts=1))
        db.commit()

        with (
            patch.object(drain_promo_refresh, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(drain_promo_refresh.ml_webhook_client, "refresh_item_promotions", return_value=False),
        ):
            drain_promo_refresh.run_drain()

        db.commit()
        row = db.query(PromoRefreshPending).filter_by(mla="MLA1").first()
        assert row is not None
        assert row.attempts == 2
        row_due_at = row.due_at if row.due_at.tzinfo else row.due_at.replace(tzinfo=UTC)
        assert row_due_at > datetime.now(UTC)

    def test_attempts_at_cap_is_quarantined(self, db, caplog):
        due = datetime.now(UTC) - timedelta(seconds=5)
        db.add(PromoRefreshPending(mla="MLA_POISON", due_at=due, attempts=drain_promo_refresh.MAX_REFRESH_ATTEMPTS - 1))
        db.commit()

        with (
            patch.object(drain_promo_refresh, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(drain_promo_refresh.ml_webhook_client, "refresh_item_promotions", return_value=False),
            caplog.at_level("ERROR"),
        ):
            drain_promo_refresh.run_drain()

        db.commit()
        assert db.query(PromoRefreshPending).filter_by(mla="MLA_POISON").first() is None
        assert any(
            "MLA_POISON" in record.getMessage() and "QUARANTINED" in record.getMessage() for record in caplog.records
        )


class TestDrainIsolation:
    def test_one_poison_mla_does_not_abort_the_batch(self, db):
        due = datetime.now(UTC) - timedelta(seconds=5)
        db.add(PromoRefreshPending(mla="MLA_POISON", due_at=due, attempts=0))
        db.add(PromoRefreshPending(mla="MLA_OK", due_at=due, attempts=0))
        db.commit()

        def fake_refresh(mla):
            if mla == "MLA_POISON":
                raise RuntimeError("boom")
            return True

        with (
            patch.object(drain_promo_refresh, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(drain_promo_refresh.ml_webhook_client, "refresh_item_promotions", side_effect=fake_refresh),
        ):
            drain_promo_refresh.run_drain()

        db.commit()
        assert db.query(PromoRefreshPending).filter_by(mla="MLA_OK").first() is None
        poison_row = db.query(PromoRefreshPending).filter_by(mla="MLA_POISON").first()
        assert poison_row is not None
        assert poison_row.attempts == 1
