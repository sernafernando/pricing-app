"""Tests for login rate limiting (app/core/rate_limit.py).

RATE_LIMIT_STORAGE_URI=memory:// is set in conftest.py before `from app.main
import app`, so the limiter in this test process binds to in-memory storage
(no Redis required, deterministic within a single process — design §9).
"""

import logging
from unittest.mock import MagicMock

import pytest

from app.core.rate_limit import client_ip_key


class TestClientIpKey:
    """Unit tests for the rate-limit key function — no app/TestClient needed."""

    def test_uses_cf_connecting_ip_when_present(self):
        request = MagicMock()
        request.headers = {"CF-Connecting-IP": "1.2.3.4"}
        request.client = MagicMock(host="9.9.9.9")
        assert client_ip_key(request) == "1.2.3.4"

    def test_falls_back_to_client_host_when_header_absent(self):
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock(host="10.0.0.5")
        assert client_ip_key(request) == "10.0.0.5"

    def test_ignores_x_forwarded_for_spoof_safety(self):
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "6.6.6.6"}
        request.client = MagicMock(host="10.0.0.5")
        assert client_ip_key(request) == "10.0.0.5"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.main import app

    app.state.limiter.reset()
    yield
    app.state.limiter.reset()


class TestLoginRateLimitEndpoint:
    """Integration tests for the rate-limited /api/auth/login route."""

    def test_requests_over_limit_return_429_with_retry_after(self, client):
        # No CF-Connecting-IP is sent by TestClient, so all 11 requests share
        # the same fallback key (client.host) -> single shared window.
        last_response = None
        for _ in range(11):
            last_response = client.post(
                "/api/auth/login",
                json={"username": "nonexistent-user", "password": "wrong"},
            )

        assert last_response.status_code == 429
        assert last_response.json()["error"]["code"] == "RATE_LIMITED"
        assert "Retry-After" in last_response.headers

    def test_fresh_client_gets_full_quota_no_cross_test_leakage(self, client):
        # If the autouse fixture above did not reset limiter state, this test
        # would inherit exhausted quota from the previous test and fail/flake.
        for _ in range(10):
            resp = client.post(
                "/api/auth/login",
                json={"username": "nonexistent-user", "password": "wrong"},
            )
            assert resp.status_code != 429

    def test_fail_open_when_storage_unreachable(self, client, caplog):
        """Design §7/§9.3: dead storage must never block login or 500.

        The `@limiter.limit(...)` decorator on the login route closes over the
        module-level `limiter` singleton directly (slowapi reads `self.limiter`
        inside the decorator, NOT `request.app.state.limiter` — that attribute
        is only consulted by the 429 handler for header injection). `self.limiter`
        is itself a `limits` strategy object (`self._limiter`) bound to a
        storage instance at `Limiter.__init__` time, so the storage must be
        broken on that bound strategy object — merely reassigning
        `Limiter._storage` afterwards has no effect, since the strategy already
        captured the original storage reference.
        """
        from limits.storage import storage_from_string
        from app.core.rate_limit import limiter as route_limiter

        original_storage = route_limiter._limiter.storage
        route_limiter._limiter.storage = storage_from_string("redis://127.0.0.1:1/0")
        try:
            with caplog.at_level(logging.WARNING, logger="slowapi"):
                resp = client.post(
                    "/api/auth/login",
                    json={"username": "nonexistent-user", "password": "wrong"},
                )
            assert resp.status_code != 500
            assert resp.status_code != 429
        finally:
            route_limiter._limiter.storage = original_storage


class TestNonGoalsGuard:
    """Requirement 5: /refresh and /register are not touched by this change."""

    def test_refresh_is_never_rate_limited(self, client):
        # 15 > the 10/minute login limit; /refresh must never 429.
        for _ in range(15):
            resp = client.post("/api/auth/refresh", json={"refresh_token": "bogus"})
            assert resp.status_code != 429

    def test_register_still_governed_by_its_own_env_gate_only(self, client):
        # Repeated calls must never surface a 429 from the new limiter; the
        # existing 403 env-gate (outside development) is unchanged.
        for _ in range(15):
            resp = client.post(
                "/api/auth/register",
                json={"username": "x", "password": "y", "nombre": "x"},
            )
            assert resp.status_code != 429
