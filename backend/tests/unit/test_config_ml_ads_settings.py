"""ml-billing-balance PR 1a -- ads kill-switch and retention window (spec ADS-7)."""

from __future__ import annotations


class TestMlAdsSettings:
    def test_ml_ads_enabled_defaults_off(self) -> None:
        """The DECLARED default, not whatever this machine's .env says."""
        from app.core.config import Settings

        assert Settings.model_fields["ML_ADS_ENABLED"].default is False

    def test_ml_ads_enabled_is_overridable_via_env(self, monkeypatch) -> None:
        from app.core.config import Settings

        monkeypatch.setenv("ML_ADS_ENABLED", "true")

        assert Settings().ML_ADS_ENABLED is True

    def test_ml_ads_retention_days_defaults_to_90(self) -> None:
        """ML keeps ad history for 90 days: the backfill window."""
        from app.core.config import Settings

        assert Settings.model_fields["ML_ADS_RETENTION_DAYS"].default == 90

    def test_ml_ads_retention_days_is_overridable_via_env(self, monkeypatch) -> None:
        from app.core.config import Settings

        monkeypatch.setenv("ML_ADS_RETENTION_DAYS", "30")

        assert Settings().ML_ADS_RETENTION_DAYS == 30

    def test_ml_ads_retention_days_cannot_exceed_what_ml_keeps(self, monkeypatch) -> None:
        import pytest
        from pydantic import ValidationError

        from app.core.config import Settings

        monkeypatch.setenv("ML_ADS_RETENTION_DAYS", "91")

        with pytest.raises(ValidationError):
            Settings()
