"""Tests for the backfill's manual CLI entry point (slice 5): `main()`
must be a complete no-op while `ML_ORDERS_OPS_ENABLED` is False, and must
never bypass `--dry-run`/`--days` parsing to reach `run_backfill` with the
wrong arguments."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.config import settings
from app.scripts import backfill_ml_orders_ops
from app.services.ml_orders_ingestion import sweep_service
from app.services.ml_orders_ingestion.backfill_service import BackfillResult


class TestFlagGate:
    def test_main_is_a_noop_when_flag_off(self, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        with patch.object(sweep_service.ml_webhook_client, "search_orders") as mock_search:
            backfill_ml_orders_ops.main(["--days", "90"])
        mock_search.assert_not_called()


class TestArgParsing:
    def test_days_and_dry_run_are_threaded_through(self, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        with patch.object(backfill_ml_orders_ops, "run_backfill") as mock_run:
            mock_run.return_value = BackfillResult(ran=True, dry_run=True)
            backfill_ml_orders_ops.main(["--days", "90..180", "--dry-run", "--seller-id", "42"])

        mock_run.assert_called_once_with(days_from=90, days_to=180, seller_id=42, dry_run=True)

    def test_single_int_days_maps_to_zero_to_n(self, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        with patch.object(backfill_ml_orders_ops, "run_backfill") as mock_run:
            mock_run.return_value = BackfillResult(ran=True)
            backfill_ml_orders_ops.main(["--days", "90"])

        mock_run.assert_called_once_with(days_from=0, days_to=90, seller_id=None, dry_run=False)

    def test_invalid_days_argument_exits_with_a_usage_message_not_a_traceback(self, monkeypatch, capsys):
        # Finding 6: an operator typo in --days must produce argparse's
        # normal usage/error output and a clean exit, never an unhandled
        # ValueError traceback.
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        with patch.object(backfill_ml_orders_ops, "run_backfill") as mock_run:
            with pytest.raises(SystemExit) as exc_info:
                backfill_ml_orders_ops.main(["--days", "180..90"])
        assert exc_info.value.code != 0
        mock_run.assert_not_called()
        captured = capsys.readouterr()
        assert "usage:" in captured.err.lower()
        assert "Traceback" not in captured.err


class TestLogSurfacesProgress:
    def test_days_completed_is_logged(self, caplog):
        import logging

        result = BackfillResult(ran=True, days_completed=5, orders_seen=12, orders_upserted=10)
        with patch.object(backfill_ml_orders_ops, "run_backfill", return_value=result):
            with caplog.at_level(logging.INFO):
                backfill_ml_orders_ops.main(["--days", "90"])

        assert "days_completed=5" in caplog.text

    def test_already_running_is_not_reported_as_flag_off(self, caplog):
        import logging

        result = BackfillResult(ran=False, error="already running")
        with patch.object(backfill_ml_orders_ops, "run_backfill", return_value=result):
            with caplog.at_level(logging.INFO):
                backfill_ml_orders_ops.main(["--days", "90"])

        assert "flag off" not in caplog.text
        assert "already running" in caplog.text
