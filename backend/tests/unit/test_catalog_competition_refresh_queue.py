"""Unit tests for catalog_competition_refresh_queue helpers (no DB)."""

from __future__ import annotations

from app.services.catalog_competition_refresh_queue import backoff_seconds


class TestBackoff:
    def test_grows_then_caps(self) -> None:
        assert backoff_seconds(1) == 60
        assert backoff_seconds(2) == 120
        assert backoff_seconds(3) == 240
        assert backoff_seconds(10) == 3600
