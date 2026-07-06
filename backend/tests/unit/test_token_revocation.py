"""Unit tests for the Redis-backed refresh-token revocation denylist.

Written strict-TDD RED-first: `app.core.token_revocation` does not exist yet
at the time these tests are authored, so collection/import fails (RED).
"""

import logging

import redis

from app.core import token_revocation


def test_revoke_then_is_revoked_round_trip():
    token_revocation.revoke_jti("jti-1", 60)
    assert token_revocation.is_revoked("jti-1") is True


def test_is_revoked_false_for_unknown_jti():
    assert token_revocation.is_revoked("never-revoked-jti") is False


def test_revoke_respects_ttl():
    """The denylist key's TTL should reflect the ttl_seconds argument."""
    token_revocation.revoke_jti("jti-ttl", 120)
    client = token_revocation._get_client()
    ttl = client.ttl(f"{token_revocation._REVOKED_PREFIX}jti-ttl")
    assert 0 < ttl <= 120


def test_revoke_noop_on_empty_jti():
    # Must not raise and must not write anything.
    token_revocation.revoke_jti("", 60)
    assert token_revocation.is_revoked("") is False


def test_revoke_noop_on_non_positive_ttl():
    token_revocation.revoke_jti("jti-zero-ttl", 0)
    assert token_revocation.is_revoked("jti-zero-ttl") is False


class _BrokenClient:
    def set(self, *args, **kwargs):
        raise redis.ConnectionError("boom")

    def exists(self, *args, **kwargs):
        raise redis.ConnectionError("boom")


def test_revoke_fail_open_on_redis_error(caplog):
    # app-namespaced loggers have propagate=False (app/core/logging.py); enable
    # propagation for the duration of this test so caplog's root handler sees it.
    app_logger = logging.getLogger("app")
    app_logger.propagate = True
    token_revocation._set_client_for_tests(_BrokenClient())
    try:
        with caplog.at_level(logging.WARNING):
            token_revocation.revoke_jti("jti-broken", 60)  # must not raise
        assert any("revocation" in r.message.lower() for r in caplog.records)
    finally:
        token_revocation._set_client_for_tests(None)
        app_logger.propagate = False


def test_is_revoked_fail_open_on_redis_error(caplog):
    app_logger = logging.getLogger("app")
    app_logger.propagate = True
    token_revocation._set_client_for_tests(_BrokenClient())
    try:
        with caplog.at_level(logging.WARNING):
            result = token_revocation.is_revoked("jti-broken")
        assert result is False
        assert any("revocation" in r.message.lower() for r in caplog.records)
    finally:
        token_revocation._set_client_for_tests(None)
        app_logger.propagate = False
