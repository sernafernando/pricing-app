"""Tests for the cron entry point (slice 3): `main()` must be a complete
no-op while `ML_ORDERS_OPS_ENABLED` is False -- the flag gate is enforced
inside `sweep_service.run_sweep`, but this test proves the SCRIPT itself
never bypasses it (e.g. by calling something else directly)."""

from __future__ import annotations

from unittest.mock import patch

from app.core.config import settings
from app.scripts import sync_ml_orders_ops


class TestFlagGate:
    def test_main_is_a_noop_when_flag_off(self, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        with patch.object(sync_ml_orders_ops.ml_webhook_client, "search_orders") as mock_search:
            sync_ml_orders_ops.main()
        mock_search.assert_not_called()

    def test_main_calls_run_sweep(self, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        with patch.object(sync_ml_orders_ops, "run_sweep") as mock_run_sweep:
            mock_run_sweep.return_value = sync_ml_orders_ops.sweep_service.SweepResult(ran=True)
            sync_ml_orders_ops.main()
        mock_run_sweep.assert_called_once()
