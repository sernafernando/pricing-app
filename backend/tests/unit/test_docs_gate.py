"""Unit tests for `_docs_urls`, the environment-gate helper for OpenAPI docs.

Covers spec Requirement 2: `/api/docs`, `/api/redoc`, `/api/openapi.json`
must be reachable only when `settings.ENVIRONMENT == "development"`.

Tests the pure helper directly (not via TestClient) because the FastAPI app
freezes `docs_url`/`redoc_url`/`openapi_url` at import time — a monkeypatch
of `settings.ENVIRONMENT` after import would not re-derive them.
"""

from app.main import _docs_urls


def test_docs_disabled_outside_development() -> None:
    urls = _docs_urls("production")
    assert urls == {"docs_url": None, "redoc_url": None, "openapi_url": None}


def test_docs_enabled_in_development() -> None:
    urls = _docs_urls("development")
    assert urls["docs_url"] == "/api/docs"
    assert urls["redoc_url"] == "/api/redoc"
    assert urls["openapi_url"] == "/api/openapi.json"


def test_docs_enabled_in_testing() -> None:
    """CI runs ENVIRONMENT=testing (.github/workflows/ci.yml) — docs must
    stay reachable there too, not just in "development"."""
    urls = _docs_urls("testing")
    assert urls["docs_url"] == "/api/docs"
    assert urls["redoc_url"] == "/api/redoc"
    assert urls["openapi_url"] == "/api/openapi.json"
