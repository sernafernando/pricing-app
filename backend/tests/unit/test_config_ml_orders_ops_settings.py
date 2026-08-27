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
