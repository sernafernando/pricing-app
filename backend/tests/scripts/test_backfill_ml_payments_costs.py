"""Tests for the backfill-payments-costs manual CLI entry point: `main()`
must be a complete no-op AND exit 0 while `ML_ORDERS_OPS_ENABLED` is
False (finding 2, post-review fix), and must exit non-zero for a genuine
failure such as "another run is already in flight"."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.config import settings
from app.scripts import backfill_ml_payments_costs
from app.services.ml_orders_ingestion.backfill_payments_costs_service import BackfillPaymentsCostsResult


class TestFlagGate:
    def test_main_is_a_noop_and_exits_zero_when_flag_off(self, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        with patch.object(backfill_ml_payments_costs, "run_backfill") as mock_run:
            mock_run.return_value = BackfillPaymentsCostsResult(ran=False)
            # main() must not raise SystemExit at all here -- a flag-off
            # no-op is a genuine success, not a failure a chained/scripted
            # invocation should see as non-zero.
            backfill_ml_payments_costs.main(["--limit", "10"])


class TestExitCodes:
    def test_already_running_exits_non_zero(self, monkeypatch):
        with patch.object(backfill_ml_payments_costs, "run_backfill") as mock_run:
            mock_run.return_value = BackfillPaymentsCostsResult(ran=False, error="already running")
            with pytest.raises(SystemExit) as exc_info:
                backfill_ml_payments_costs.main(["--limit", "10"])
        assert exc_info.value.code != 0

    def test_an_error_during_a_real_run_exits_non_zero(self, monkeypatch):
        with patch.object(backfill_ml_payments_costs, "run_backfill") as mock_run:
            mock_run.return_value = BackfillPaymentsCostsResult(ran=True, error="ValueError: boom")
            with pytest.raises(SystemExit) as exc_info:
                backfill_ml_payments_costs.main(["--limit", "10"])
        assert exc_info.value.code != 0

    def test_a_clean_run_does_not_exit_with_an_error_code(self, monkeypatch):
        with patch.object(backfill_ml_payments_costs, "run_backfill") as mock_run:
            mock_run.return_value = BackfillPaymentsCostsResult(ran=True, order_candidates=3, orders_sealed=3)
            backfill_ml_payments_costs.main(["--limit", "10"])  # must not raise


class TestArgParsing:
    def test_limit_and_dry_run_are_threaded_through(self, monkeypatch):
        with patch.object(backfill_ml_payments_costs, "run_backfill") as mock_run:
            mock_run.return_value = BackfillPaymentsCostsResult(ran=True, dry_run=True)
            backfill_ml_payments_costs.main(["--limit", "250", "--dry-run"])

        mock_run.assert_called_once_with(limit=250, dry_run=True)

    def test_default_limit_is_used_when_omitted(self, monkeypatch):
        with patch.object(backfill_ml_payments_costs, "run_backfill") as mock_run:
            mock_run.return_value = BackfillPaymentsCostsResult(ran=True)
            backfill_ml_payments_costs.main([])

        mock_run.assert_called_once_with(limit=backfill_ml_payments_costs.DEFAULT_LIMIT, dry_run=False)


class TestLogSurfacesProgress:
    def test_budget_exhausted_flags_are_logged(self, caplog):
        import logging

        result = BackfillPaymentsCostsResult(
            ran=True,
            order_candidates=10,
            orders_sealed=4,
            payments_budget_exhausted=True,
            shipment_candidates=5,
            shipment_costs_synced=5,
            costs_budget_exhausted=False,
        )
        with patch.object(backfill_ml_payments_costs, "run_backfill", return_value=result):
            with caplog.at_level(logging.INFO):
                backfill_ml_payments_costs.main(["--limit", "10"])

        assert "payments_budget_exhausted=True" in caplog.text
        assert "costs_budget_exhausted=False" in caplog.text
