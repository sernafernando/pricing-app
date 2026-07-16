"""Unit/integration tests for the global exception handler header forwarding.

Covers review fix: `http_exception_handler` must forward `exc.headers` onto
the JSONResponse (RFC 7231 `Allow` on 405, `WWW-Authenticate` on 401), and a
405 (method not allowed) must be mapped to a `METHOD_NOT_ALLOWED` error code
instead of falling back to the generic `INTERNAL_ERROR`.
"""

from fastapi import Depends

from app.api.deps import require_dev_or_test
from app.core.config import settings
from app.main import app


BASE = "/api/administracion/compras"


def test_method_not_allowed_returns_allow_header_and_error_code(client, monkeypatch) -> None:
    """GET on a POST-only route returns 405 with an Allow header + METHOD_NOT_ALLOWED."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    response = client.get(f"{BASE}/testing/wipe-compras")

    assert response.status_code == 405
    assert "allow" in {k.lower() for k in response.headers.keys()}
    assert "POST" in response.headers.get("allow", "")
    body = response.json()
    assert body["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_env_gated_404_is_byte_identical_to_unmatched_route(client, monkeypatch) -> None:
    """An explicit bare `HTTPException(404)` must be byte-identical to Starlette's
    own unmatched-route 404 — that is why the handler is registered on the base
    `StarletteHTTPException` and must survive the header-forwarding change
    (`headers=None` outside the gate path).

    This used to be exercised through the wipe-compras env-gate. That gate was
    removed on 2026-07-16 (recorded decision 2026-06-10 keeps the endpoint
    reachable in production), so the invariant is pinned here against
    `require_dev_or_test` itself — the helper any future testing-only route would
    use — mounted on a throwaway probe route.
    """
    probe_path = "/api/_probe-env-gated-404"

    app.post(probe_path, dependencies=[Depends(require_dev_or_test)])(lambda: {"ok": True})
    try:
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")

        response = client.post(probe_path, json={})
        control = client.post("/api/this-route-does-not-exist-xyz", json={})

        assert response.status_code == control.status_code == 404
        assert response.json() == control.json()
        assert response.headers.get("content-type") == control.headers.get("content-type")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != probe_path]
