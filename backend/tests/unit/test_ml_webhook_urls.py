"""Regression tests for the ml-webhook base-URL extraction (audit M-3).

The internal ml-webhook host was hardcoded in three call sites; it now derives
from `settings.ML_WEBHOOK_BASE_URL`. These tests pin that the derived URLs match
the original values (no behavior change) and that the client honors config.
"""

from app.core.config import settings


def test_base_url_default_is_the_internal_host():
    assert settings.ML_WEBHOOK_BASE_URL == "https://ml-webhook.gaussonline.com.ar"


def test_derived_render_urls_match_original_hardcoded_values():
    from app.services.ml_webhook_service import ML_WEBHOOK_RENDER_URL as svc_render
    from app.routers.seriales_shared import ML_WEBHOOK_RENDER_URL as ser_render

    expected = "https://ml-webhook.gaussonline.com.ar/api/ml/render"
    assert svc_render == expected
    assert ser_render == expected


def test_client_base_url_matches_setting():
    from app.services.ml_webhook_client import MLWebhookClient

    assert MLWebhookClient().base_url == settings.ML_WEBHOOK_BASE_URL


def test_client_honors_config_override(monkeypatch):
    """A per-env override of the base URL is picked up by a new client instance."""
    from app.services.ml_webhook_client import MLWebhookClient

    monkeypatch.setattr(settings, "ML_WEBHOOK_BASE_URL", "https://ml-webhook.staging.example", raising=False)
    assert MLWebhookClient().base_url == "https://ml-webhook.staging.example"
