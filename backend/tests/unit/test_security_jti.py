"""Unit tests for jti claim issuance and the remaining_ttl_seconds helper.

Strict-TDD RED-first: written before `security.py` gains a `jti` claim and a
`remaining_ttl_seconds` helper.
"""

from datetime import UTC, datetime, timedelta

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    remaining_ttl_seconds,
)


def test_access_token_has_jti():
    token = create_access_token(data={"sub": "someone"})
    payload = decode_token(token)
    assert payload.get("jti")
    assert isinstance(payload["jti"], str)


def test_refresh_token_has_jti():
    token = create_refresh_token(data={"sub": "someone"})
    payload = decode_token(token)
    assert payload.get("jti")
    assert isinstance(payload["jti"], str)


def test_jtis_are_distinct_across_calls():
    t1 = create_access_token(data={"sub": "someone"})
    t2 = create_access_token(data={"sub": "someone"})
    p1 = decode_token(t1)
    p2 = decode_token(t2)
    assert p1["jti"] != p2["jti"]


def test_token_without_jti_still_decodes():
    """Pre-deploy (in-flight) tokens carry no jti; decode_token must not choke."""
    import jwt

    from app.core.config import settings

    payload = {
        "sub": "legacy-user",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "iss": "pricing-app",
        "aud": "pricing-app-api",
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    decoded = decode_token(token)
    assert decoded is not None
    assert decoded.get("jti") is None


def test_remaining_ttl_seconds_positive_for_live_exp():
    payload = {"exp": (datetime.now(UTC) + timedelta(minutes=10)).timestamp()}
    ttl = remaining_ttl_seconds(payload)
    assert 0 < ttl <= 600


def test_remaining_ttl_seconds_clamped_to_zero_for_past_exp():
    payload = {"exp": (datetime.now(UTC) - timedelta(minutes=10)).timestamp()}
    assert remaining_ttl_seconds(payload) == 0


def test_remaining_ttl_seconds_zero_when_exp_missing():
    assert remaining_ttl_seconds({}) == 0
