"""Unit/integration tests for the global exception handler header forwarding.

Covers review fix: `http_exception_handler` must forward `exc.headers` onto
the JSONResponse (RFC 7231 `Allow` on 405, `WWW-Authenticate` on 401), and a
405 (method not allowed) must be mapped to a `METHOD_NOT_ALLOWED` error code
instead of falling back to the generic `INTERNAL_ERROR`.
"""

from app.core.config import settings


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


def test_wipe_gate_still_byte_identical_404_outside_dev(client, monkeypatch) -> None:
    """Regression: the wipe-gate byte-identical-404 behavior must survive the
    header-forwarding change (headers=None outside the gate path)."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    response = client.post(
        f"{BASE}/testing/wipe-compras",
        json={"confirmacion": "WIPE", "incluir_caja_banco": False},
        headers={"Authorization": "Bearer invalid"},
    )
    control = client.post("/api/this-route-does-not-exist-xyz", json={})

    assert response.status_code == control.status_code == 404
    assert response.json() == control.json()
    assert response.headers.get("content-type") == control.headers.get("content-type")
