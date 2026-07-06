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

from app.core import token_revocation
from app.core.security import decode_token
from tests.conftest import TEST_PASSWORD, make_access_token, make_refresh_token


# ---------------------------------------------------------------------------
# JWT-01: Login success
# ---------------------------------------------------------------------------


class TestLoginSuccess:
    """JWT-01: Valid user + password -> 200, returns tokens."""

    def test_login_with_username(self, client, active_user):
        response = client.post(
            "/api/auth/login",
            json={
                "username": active_user.username,
                "password": TEST_PASSWORD,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"
        assert body["usuario"]["username"] == active_user.username

    def test_login_with_email(self, client, active_user):
        response = client.post(
            "/api/auth/login",
            json={
                "username": active_user.email,
                "password": TEST_PASSWORD,
            },
        )
        assert response.status_code == 200
        assert "access_token" in response.json()


# ---------------------------------------------------------------------------
# JWT-02: Login invalid password
# ---------------------------------------------------------------------------


class TestLoginFailure:
    """JWT-02: Wrong password -> 401."""

    def test_wrong_password(self, client, active_user):
        response = client.post(
            "/api/auth/login",
            json={
                "username": active_user.username,
                "password": "WrongPassword!",
            },
        )
        assert response.status_code == 401

    def test_nonexistent_user(self, client):
        response = client.post(
            "/api/auth/login",
            json={
                "username": "nobody",
                "password": "whatever",
            },
        )
        assert response.status_code == 401

    def test_inactive_user_cannot_login(self, client, inactive_user):
        """Disabled user should be rejected at login."""
        response = client.post(
            "/api/auth/login",
            json={
                "username": inactive_user.username,
                "password": TEST_PASSWORD,
            },
        )
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
        response = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.real.token"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# JWT-05: Refresh success
# ---------------------------------------------------------------------------


class TestRefreshSuccess:
    """JWT-05: Valid refresh token -> 200, new access token."""

    def test_refresh_returns_new_access_token(self, client, active_user):
        refresh = make_refresh_token(active_user)
        response = client.post(
            "/api/auth/refresh",
            json={
                "refresh_token": refresh,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        # Rotation contract (REV-05): a new refresh_token is also returned.
        assert "refresh_token" in body


# ---------------------------------------------------------------------------
# JWT-06: Refresh with invalid/expired token
# ---------------------------------------------------------------------------


class TestRefreshInvalid:
    """JWT-06: Expired or tampered refresh -> 401."""

    def test_refresh_with_garbage(self, client):
        response = client.post(
            "/api/auth/refresh",
            json={
                "refresh_token": "garbage.token.here",
            },
        )
        assert response.status_code == 401

    def test_refresh_with_empty_string(self, client):
        response = client.post(
            "/api/auth/refresh",
            json={
                "refresh_token": "",
            },
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# JWT-07: Wrong token type for refresh
# ---------------------------------------------------------------------------


class TestRefreshWrongTokenType:
    """JWT-07: Access token used as refresh -> 401."""

    def test_access_token_rejected_as_refresh(self, client, active_user):
        access = make_access_token(active_user)
        response = client.post(
            "/api/auth/refresh",
            json={
                "refresh_token": access,
            },
        )
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
        response = client.post(
            "/api/auth/refresh",
            json={
                "refresh_token": refresh,
            },
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# REV-01: Revoked jti -> 401 (mandated strict-TDD RED gate)
# ---------------------------------------------------------------------------


class TestRevokedRefreshRejected:
    """REV-01: A refresh token whose jti was revoked must be rejected."""

    def test_revoked_refresh_token_rejected(self, client, active_user):
        refresh = make_refresh_token(active_user)
        payload = decode_token(refresh)
        token_revocation.revoke_jti(payload["jti"], 3600)

        response = client.post(
            "/api/auth/refresh",
            json={
                "refresh_token": refresh,
            },
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# REV-02/REV-03: /auth/logout revokes the refresh token
# ---------------------------------------------------------------------------


class TestLogout:
    """REV-02: Logout revokes; REV-03: wrong token type rejected."""

    def test_logout_then_refresh_rejected(self, client, active_user):
        refresh = make_refresh_token(active_user)

        logout_response = client.post(
            "/api/auth/logout",
            json={
                "refresh_token": refresh,
            },
        )
        assert logout_response.status_code == 200

        refresh_response = client.post(
            "/api/auth/refresh",
            json={
                "refresh_token": refresh,
            },
        )
        assert refresh_response.status_code == 401

    def test_logout_with_access_token_rejected(self, client, active_user):
        access = make_access_token(active_user)
        response = client.post(
            "/api/auth/logout",
            json={
                "refresh_token": access,
            },
        )
        assert response.status_code == 401
        error = response.json()["error"]
        assert error["code"] == "INVALID_TOKEN_TYPE"

        # No denylist entry should have been written for the access token's jti.
        payload = decode_token(access)
        assert token_revocation.is_revoked(payload["jti"]) is False


# ---------------------------------------------------------------------------
# REV-04/REV-05: Rotation on /auth/refresh
# ---------------------------------------------------------------------------


class TestRefreshRotation:
    """REV-04: rotation issues new + rejects old; REV-05: response contract."""

    def test_rotation_issues_new_and_rejects_old(self, client, active_user):
        refresh = make_refresh_token(active_user)

        first = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert first.status_code == 200
        body = first.json()
        new_refresh = body["refresh_token"]
        assert new_refresh != refresh

        # Old token is now revoked -> rejected.
        second_with_old = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert second_with_old.status_code == 401

        # New token works.
        second_with_new = client.post("/api/auth/refresh", json={"refresh_token": new_refresh})
        assert second_with_new.status_code == 200

    def test_rotation_response_contract(self, client, active_user):
        refresh = make_refresh_token(active_user)
        response = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"


# ---------------------------------------------------------------------------
# REV-06: In-flight (pre-deploy) token without jti still refreshes
# ---------------------------------------------------------------------------


class TestInFlightTokenWithoutJti:
    """REV-06: A refresh token issued before this change (no jti) still works."""

    def test_refresh_without_jti_still_succeeds(self, client, active_user):
        import jwt as pyjwt
        from datetime import UTC, datetime, timedelta

        from app.core.config import settings

        payload = {
            "sub": active_user.username,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iss": "pricing-app",
            "aud": "pricing-app-api",
            "type": "refresh",
        }
        legacy_refresh = pyjwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

        response = client.post(
            "/api/auth/refresh",
            json={
                "refresh_token": legacy_refresh,
            },
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# REV-07/REV-08: Fail-open on Redis unavailability
# ---------------------------------------------------------------------------


class _BrokenRedisClient:
    def set(self, *args, **kwargs):
        import redis

        raise redis.ConnectionError("boom")

    def exists(self, *args, **kwargs):
        import redis

        raise redis.ConnectionError("boom")


class TestFailOpen:
    """REV-07: refresh proceeds when Redis is down; REV-08: logout too."""

    def test_refresh_proceeds_when_redis_down(self, client, active_user, caplog):
        import logging

        refresh = make_refresh_token(active_user)
        token_revocation._set_client_for_tests(_BrokenRedisClient())
        app_logger = logging.getLogger("app")
        app_logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING):
                response = client.post(
                    "/api/auth/refresh",
                    json={
                        "refresh_token": refresh,
                    },
                )
            assert response.status_code == 200
            assert any("revocation" in r.message.lower() for r in caplog.records)
        finally:
            app_logger.propagate = False

    def test_logout_proceeds_when_redis_down(self, client, active_user, caplog):
        import logging

        refresh = make_refresh_token(active_user)
        token_revocation._set_client_for_tests(_BrokenRedisClient())
        app_logger = logging.getLogger("app")
        app_logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING):
                response = client.post(
                    "/api/auth/logout",
                    json={
                        "refresh_token": refresh,
                    },
                )
            assert response.status_code == 200
            assert any("revocation" in r.message.lower() for r in caplog.records)
        finally:
            app_logger.propagate = False


class TestRefreshKeyIsolation:
    """M-2: refresh token signed with the dedicated REFRESH_SECRET_KEY validates.

    RED gate: on current code /auth/refresh decodes with SECRET_KEY only, so a
    token signed with a distinct refresh key is rejected (401). After the change
    decode_refresh_token tries the refresh key first and accepts it (200).
    """

    def test_refresh_signed_with_distinct_refresh_key_succeeds(self, client, active_user, monkeypatch):
        import jwt as pyjwt
        from datetime import UTC, datetime, timedelta
        from app.core.config import settings

        distinct_key = "a-distinct-refresh-key-not-equal-to-secret-key"
        # Per-test only: pytest reverts at teardown; does NOT touch fakeredis /
        # rate-limiter autouse fixtures. raising=False so it also runs on code
        # where the attribute does not yet exist (RED phase).
        monkeypatch.setattr(settings, "REFRESH_SECRET_KEY", distinct_key, raising=False)

        payload = {
            "sub": active_user.username,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iss": "pricing-app",
            "aud": "pricing-app-api",
            "type": "refresh",
            "jti": "isolation-red-gate-jti",
        }
        refresh = pyjwt.encode(payload, distinct_key, algorithm=settings.ALGORITHM)

        response = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert response.status_code == 200

    def test_refresh_signed_with_secret_key_still_validates_via_fallback(self, client, active_user, monkeypatch):
        import jwt as pyjwt
        from datetime import UTC, datetime, timedelta
        from app.core.config import settings

        monkeypatch.setattr(settings, "REFRESH_SECRET_KEY", "a-distinct-refresh-key", raising=False)
        # Signed with SECRET_KEY (the OLD/in-flight key), NOT the refresh key.
        payload = {
            "sub": active_user.username,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iss": "pricing-app",
            "aud": "pricing-app-api",
            "type": "refresh",
            "jti": "fallback-jti",
        }
        legacy = pyjwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

        response = client.post("/api/auth/refresh", json={"refresh_token": legacy})
        assert response.status_code == 200

    def test_refresh_signed_with_wrong_key_rejected(self, client, active_user, monkeypatch):
        import jwt as pyjwt
        from datetime import UTC, datetime, timedelta
        from app.core.config import settings

        monkeypatch.setattr(settings, "REFRESH_SECRET_KEY", "the-real-refresh-key", raising=False)
        payload = {
            "sub": active_user.username,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iss": "pricing-app",
            "aud": "pricing-app-api",
            "type": "refresh",
            "jti": "wrong-key-jti",
        }
        # Signed with neither the refresh key nor SECRET_KEY.
        forged = pyjwt.encode(payload, "a-totally-unrelated-key", algorithm=settings.ALGORITHM)

        response = client.post("/api/auth/refresh", json={"refresh_token": forged})
        assert response.status_code == 401

    def test_rotation_and_revocation_intact_with_distinct_refresh_key(self, client, active_user, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "REFRESH_SECRET_KEY", "a-distinct-refresh-key", raising=False)
        # make_refresh_token now signs with the distinct refresh key.
        refresh = make_refresh_token(active_user)

        first = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert first.status_code == 200
        new_refresh = first.json()["refresh_token"]
        assert new_refresh != refresh

        # Old token revoked by rotation -> rejected.
        reused = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert reused.status_code == 401

        # New (distinct-key-signed) token works.
        again = client.post("/api/auth/refresh", json={"refresh_token": new_refresh})
        assert again.status_code == 200
