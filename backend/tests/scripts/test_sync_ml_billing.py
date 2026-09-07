"""Exit-code contract for the billing sweep cron entry point (corte 3)."""

from __future__ import annotations

from unittest import mock

from app.scripts import sync_ml_billing
from app.services.ml_billing.billing_sweep_service import BillingSweepResult


def test_flag_off_or_not_ran_exits_zero() -> None:
    with mock.patch.object(sync_ml_billing, "run_billing_sweep", return_value=BillingSweepResult(ran=False)):
        assert sync_ml_billing.main() == 0


def test_successful_sweep_exits_zero() -> None:
    result = BillingSweepResult(ran=True, period_key="2026-09-01", charges_seen=3, charges_upserted=3)
    with mock.patch.object(sync_ml_billing, "run_billing_sweep", return_value=result):
        assert sync_ml_billing.main() == 0


def test_failed_sweep_exits_nonzero() -> None:
    result = BillingSweepResult(ran=True, period_key="2026-09-01", error="boom")
    with mock.patch.object(sync_ml_billing, "run_billing_sweep", return_value=result):
        assert sync_ml_billing.main() == 1


def test_stopped_early_sweep_exits_nonzero() -> None:
    result = BillingSweepResult(ran=True, period_key="2026-09-01", stopped_early=True)
    with mock.patch.object(sync_ml_billing, "run_billing_sweep", return_value=result):
        assert sync_ml_billing.main() == 1
