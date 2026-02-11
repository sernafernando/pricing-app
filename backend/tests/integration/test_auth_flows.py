"""
Integration tests for authentication flows.

Covers JWT test matrix cases JWT-01 through JWT-08 (P0):
- Login success / failure
- Access token on protected endpoints
- Refresh token flow (success, expired, wrong type)
- Disabled user behavior

Run:
    pytest tests/integration/test_auth_flows.py -v
"""

import pytest

from tests.conftest import TEST_PASSWORD, make_access_token, make_refresh_token


# ---------------------------------------------------------------------------
# JWT-01: Login success
# ---------------------------------------------------------------------------


class TestLoginSuccess:
    """JWT-01: Valid user + password -> 200, returns tokens."""

    def test_login_with_username(self, client, active_user):
        response = client.post("/api/auth/login", json={
            "username": active_user.username,
            "password": TEST_PASSWORD,
        })
        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"
        assert body["usuario"]["username"] == active_user.username

    def test_login_with_email(self, client, active_user):
        response = client.post("/api/auth/login", json={
            "username": active_user.email,
            "password": TEST_PASSWORD,
        })
        assert response.status_code == 200
        assert "access_token" in response.json()


# ---------------------------------------------------------------------------
# JWT-02: Login invalid password
# ---------------------------------------------------------------------------


class TestLoginFailure:
    """JWT-02: Wrong password -> 401."""

    def test_wrong_password(self, client, active_user):
        response = client.post("/api/auth/login", json={
            "username": active_user.username,
            "password": "WrongPassword!",
        })
        assert response.status_code == 401

    def test_nonexistent_user(self, client):
        response = client.post("/api/auth/login", json={
            "username": "nobody",
            "password": "whatever",
        })
        assert response.status_code == 401

    def test_inactive_user_cannot_login(self, client, inactive_user):
        """Disabled user should be rejected at login."""
        response = client.post("/api/auth/login", json={
            "username": inactive_user.username,
            "password": TEST_PASSWORD,
        })
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# JWT-03: Access token on protected endpoint
# ---------------------------------------------------------------------------


class TestProtectedEndpoint:
    """JWT-03: Valid access token -> 200 on /auth/me."""

    def test_me_with_valid_token(self, client, auth_headers, active_user):
        response = client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["username"] == active_user.username
        assert body["activo"] is True


# ---------------------------------------------------------------------------
# JWT-04: Missing token on protected endpoint
# ---------------------------------------------------------------------------


class TestMissingToken:
    """JWT-04: No token -> 401/403 on protected endpoint."""

    def test_me_without_token(self, client):
        response = client.get("/api/auth/me")
        assert response.status_code in (401, 403)

    def test_me_with_garbage_token(self, client):
        response = client.get("/api/auth/me", headers={
            "Authorization": "Bearer not.a.real.token"
        })
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# JWT-05: Refresh success
# ---------------------------------------------------------------------------


class TestRefreshSuccess:
    """JWT-05: Valid refresh token -> 200, new access token."""

    def test_refresh_returns_new_access_token(self, client, active_user):
        refresh = make_refresh_token(active_user)
        response = client.post("/api/auth/refresh", json={
            "refresh_token": refresh,
        })
        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"


# ---------------------------------------------------------------------------
# JWT-06: Refresh with invalid/expired token
# ---------------------------------------------------------------------------


class TestRefreshInvalid:
    """JWT-06: Expired or tampered refresh -> 401."""

    def test_refresh_with_garbage(self, client):
        response = client.post("/api/auth/refresh", json={
            "refresh_token": "garbage.token.here",
        })
        assert response.status_code == 401

    def test_refresh_with_empty_string(self, client):
        response = client.post("/api/auth/refresh", json={
            "refresh_token": "",
        })
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# JWT-07: Wrong token type for refresh
# ---------------------------------------------------------------------------


class TestRefreshWrongTokenType:
    """JWT-07: Access token used as refresh -> 401."""

    def test_access_token_rejected_as_refresh(self, client, active_user):
        access = make_access_token(active_user)
        response = client.post("/api/auth/refresh", json={
            "refresh_token": access,
        })
        assert response.status_code == 401
        error = response.json()["error"]
        assert error["code"] == "INVALID_TOKEN_TYPE"
        assert "refresh" in error["message"].lower()


# ---------------------------------------------------------------------------
# JWT-08: Disabled user cannot refresh
# ---------------------------------------------------------------------------


class TestDisabledUserRefresh:
    """JWT-08: Inactive user's refresh token -> 401."""

    def test_inactive_user_refresh_rejected(self, client, inactive_user):
        refresh = make_refresh_token(inactive_user)
        response = client.post("/api/auth/refresh", json={
            "refresh_token": refresh,
        })
        assert response.status_code == 401
