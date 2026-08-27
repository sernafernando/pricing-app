"""RED/GREEN for the ML operations kill-switch (slice 1, task 3)."""

from __future__ import annotations

from app.core.config import settings


class TestMlOrdersOpsSettings:
    def test_ml_orders_ops_enabled_defaults_off(self) -> None:
        assert settings.ML_ORDERS_OPS_ENABLED is False

    def test_ml_orders_ops_enabled_is_overridable_via_env(self, monkeypatch) -> None:
        from app.core.config import Settings

        monkeypatch.setenv("ML_ORDERS_OPS_ENABLED", "true")
        overridden = Settings()

        assert overridden.ML_ORDERS_OPS_ENABLED is True

    def test_ml_orders_ops_window_days_defaults_within_agreed_range(self) -> None:
        """Rolling window boundary (obs #1820): 90-180 days, user-agreed."""
        assert 90 <= settings.ML_ORDERS_OPS_WINDOW_DAYS <= 180

    def test_ml_orders_ops_window_days_is_overridable_via_env(self, monkeypatch) -> None:
        from app.core.config import Settings

        monkeypatch.setenv("ML_ORDERS_OPS_WINDOW_DAYS", "120")
        overridden = Settings()

        assert overridden.ML_ORDERS_OPS_WINDOW_DAYS == 120
