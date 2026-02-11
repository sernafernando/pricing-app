"""
Integration tests for the standardized error response contract.

Every API error MUST return:
    {"error": {"code": "MACHINE_READABLE", "message": "Human-readable"}}

These tests verify the shape is consistent across auth, pricing, and sync
endpoints for common error scenarios.

Run:
    pytest tests/integration/test_error_contract.py -v
"""

import pytest

from tests.conftest import TEST_PASSWORD, make_access_token


def assert_error_shape(response) -> dict:
    """Assert response follows the standard error envelope and return the error dict."""
    body = response.json()
    assert "error" in body, f"Missing 'error' key in response: {body}"
    error = body["error"]
    assert "code" in error, f"Missing 'code' in error: {error}"
    assert "message" in error, f"Missing 'message' in error: {error}"
    assert isinstance(error["code"], str)
    assert isinstance(error["message"], str)
    assert len(error["code"]) > 0
    assert len(error["message"]) > 0
    return error


class TestAuthErrorContract:
    """Auth errors return standard shape with specific error codes."""

    def test_login_wrong_password_shape(self, client, active_user):
        response = client.post("/api/auth/login", json={
            "username": active_user.username,
            "password": "WrongPassword!",
        })
        assert response.status_code == 401
        error = assert_error_shape(response)
        assert error["code"] == "INVALID_CREDENTIALS"

    def test_login_inactive_user_shape(self, client, inactive_user):
        response = client.post("/api/auth/login", json={
            "username": inactive_user.username,
            "password": TEST_PASSWORD,
        })
        assert response.status_code == 401
        error = assert_error_shape(response)
        assert error["code"] == "INACTIVE_USER"

    def test_missing_token_shape(self, client):
        response = client.get("/api/auth/me")
        assert response.status_code in (401, 403)
        # FastAPI's HTTPBearer may return 403 with its own format,
        # but our handler normalizes it
        assert_error_shape(response)

    def test_garbage_token_shape(self, client):
        response = client.get("/api/auth/me", headers={
            "Authorization": "Bearer garbage.token.here"
        })
        assert response.status_code == 401
        error = assert_error_shape(response)
        assert error["code"] == "INVALID_TOKEN"

    def test_refresh_wrong_type_shape(self, client, active_user):
        access = make_access_token(active_user)
        response = client.post("/api/auth/refresh", json={
            "refresh_token": access,
        })
        assert response.status_code == 401
        error = assert_error_shape(response)
        assert error["code"] == "INVALID_TOKEN_TYPE"


class TestPricingErrorContract:
    """Pricing errors (legacy string detail) are normalized by global handler."""

    def test_pricing_auth_guard_shape(self, client):
        response = client.post("/api/precios/calcular-por-markup", json={
            "item_id": 1,
            "pricelist_id": 4,
            "markup_objetivo": 30.0,
        })
        assert response.status_code in (401, 403)
        assert_error_shape(response)

    def test_pricing_not_found_shape(self, client, auth_headers):
        response = client.post(
            "/api/precios/calcular-por-markup",
            json={"item_id": 999999, "pricelist_id": 4, "markup_objetivo": 30.0},
            headers=auth_headers,
        )
        assert response.status_code == 404
        error = assert_error_shape(response)
        assert error["code"] == "NOT_FOUND"


class TestSyncErrorContract:
    """Sync errors follow the standard shape."""

    def test_sync_auth_guard_shape(self, client):
        response = client.post("/api/sync-ml/precios")
        assert response.status_code in (401, 403)
        assert_error_shape(response)
