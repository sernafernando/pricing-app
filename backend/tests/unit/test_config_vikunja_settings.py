"""RED/GREEN for the Vikunja settings (sdd/tickets-sync-vikunja PR 1, task 1.8/1.9)."""

from __future__ import annotations

from app.core.config import settings


class TestVikunjaSettings:
    def test_sync_enabled_defaults_off(self) -> None:
        assert settings.TICKETS_VIKUNJA_SYNC_ENABLED is False

    def test_connection_settings_exist(self) -> None:
        # Optional/None-defaulted — just confirm the attributes exist.
        assert hasattr(settings, "VIKUNJA_BASE_URL")
        assert hasattr(settings, "VIKUNJA_TOKEN")
        assert hasattr(settings, "VIKUNJA_PROJECT_ID")
