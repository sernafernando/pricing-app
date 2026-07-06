"""Unit tests for decode_refresh_token (M-2: dedicated refresh signing key).

Direct coverage of the dual-key decoder: refresh_secret_key first, SECRET_KEY
fallback second. Complements the endpoint-level RED gate in
tests/integration/test_auth_flows.py::TestRefreshKeyIsolation.
"""

import jwt as pyjwt
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.security import create_refresh_token, decode_refresh_token


def test_decode_refresh_token_accepts_refresh_key(monkeypatch):
    monkeypatch.setattr(settings, "REFRESH_SECRET_KEY", "a-distinct-refresh-key", raising=False)

    token = create_refresh_token(data={"sub": "someone"})
    payload = decode_refresh_token(token)

    assert payload is not None
    assert payload["sub"] == "someone"
    assert payload["type"] == "refresh"


def test_decode_refresh_token_accepts_secret_key_fallback(monkeypatch):
    monkeypatch.setattr(settings, "REFRESH_SECRET_KEY", "a-distinct-refresh-key", raising=False)

    payload_in = {
        "sub": "someone",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "iss": "pricing-app",
        "aud": "pricing-app-api",
        "type": "refresh",
        "jti": "fallback-unit-jti",
    }
    legacy = pyjwt.encode(payload_in, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    payload = decode_refresh_token(legacy)

    assert payload is not None
    assert payload["sub"] == "someone"


def test_decode_refresh_token_rejects_wrong_key(monkeypatch):
    monkeypatch.setattr(settings, "REFRESH_SECRET_KEY", "the-real-refresh-key", raising=False)

    payload_in = {
        "sub": "someone",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "iss": "pricing-app",
        "aud": "pricing-app-api",
        "type": "refresh",
        "jti": "wrong-key-unit-jti",
    }
    forged = pyjwt.encode(payload_in, "a-totally-unrelated-key", algorithm=settings.ALGORITHM)

    assert decode_refresh_token(forged) is None


def test_decode_refresh_token_returns_none_for_garbage():
    assert decode_refresh_token("garbage.token.here") is None


def test_unset_refresh_key_is_secret_key_parity(monkeypatch):
    monkeypatch.setattr(settings, "REFRESH_SECRET_KEY", None, raising=False)

    assert settings.refresh_secret_key == settings.SECRET_KEY

    payload_in = {
        "sub": "someone",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "iss": "pricing-app",
        "aud": "pricing-app-api",
        "type": "refresh",
        "jti": "parity-unit-jti",
    }
    legacy = pyjwt.encode(payload_in, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    payload = decode_refresh_token(legacy)

    assert payload is not None
    assert payload["sub"] == "someone"
