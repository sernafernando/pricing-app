"""Tests for the cron entry point (slice 3): `main()` must be a complete
no-op while `ML_ORDERS_OPS_ENABLED` is False -- the flag gate is enforced
inside `sweep_service.run_sweep`, but this test proves the SCRIPT itself
never bypasses it (e.g. by calling something else directly)."""

from __future__ import annotations

from unittest.mock import patch

from app.core.config import settings
from app.scripts import sync_ml_orders_ops
from app.services.ml_orders_ingestion import sweep_service


class TestFlagGate:
    def test_main_is_a_noop_when_flag_off(self, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        with patch.object(sweep_service.ml_webhook_client, "search_orders") as mock_search:
            sync_ml_orders_ops.main()
        mock_search.assert_not_called()

    def test_main_calls_run_sweep(self, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        with patch.object(sync_ml_orders_ops, "run_sweep") as mock_run_sweep:
            mock_run_sweep.return_value = sweep_service.SweepResult(ran=True)
            sync_ml_orders_ops.main()
        mock_run_sweep.assert_called_once()


class TestCronLogSurfacesTheEscapeHatch:
    """The unenumerable counter exists so a stuck window is visible instead
    of silent. The cron log is where ops actually looks."""

    def test_unenumerable_count_is_logged(self, caplog) -> None:
        import logging

        from app.scripts import sync_ml_orders_ops
        from app.services.ml_orders_ingestion.sweep_service import SweepResult

        result = SweepResult(ran=True)
        result.windows_unenumerable = 3

        with patch.object(sync_ml_orders_ops, "run_sweep", return_value=result):
            with caplog.at_level(logging.INFO):
                sync_ml_orders_ops.main()

        assert "unenumerable=3" in caplog.text

    def test_already_running_is_not_reported_as_flag_off(self, caplog) -> None:
        import logging

        from app.scripts import sync_ml_orders_ops
        from app.services.ml_orders_ingestion.sweep_service import SweepResult

        with patch.object(
            sync_ml_orders_ops, "run_sweep", return_value=SweepResult(ran=False, error="already running")
        ):
            with caplog.at_level(logging.INFO):
                sync_ml_orders_ops.main()

        assert "flag off" not in caplog.text
        assert "already running" in caplog.text
