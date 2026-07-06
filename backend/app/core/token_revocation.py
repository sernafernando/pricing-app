"""Refresh-token revocation denylist — raw Redis, fail-open by design.

Mirrors app/core/rate_limit.py's discipline: a Redis outage must NEVER hang or
fail-close the auth path. Aggressive socket timeouts (0.25s) bound the blocking
window; any Redis error is swallowed + logged, and `is_revoked` returns False
(allow through). Revocation is therefore best-effort during an outage — an
accepted, documented residual risk (M-1 asks for revocability, not a hard SPOF).

Key scheme: `revoked_jti:<jti>` -> "1", with EX = remaining token lifetime, so the
denylist entry auto-expires exactly when the token would have expired anyway. No
cleanup job; the denylist cannot grow unbounded.
"""

import logging
from typing import Optional

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_REVOKED_PREFIX = "revoked_jti:"

# Module-level singleton, lazily built so tests can inject a fake before first use.
_client: Optional[redis.Redis] = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=0.25,  # bound connect blocking (fail-open)
            socket_timeout=0.25,  # bound read/write blocking (fail-open)
        )
    return _client


def _set_client_for_tests(client: Optional[redis.Redis]) -> None:
    """Test seam: swap in a fakeredis/in-memory client, or None to reset."""
    global _client
    _client = client


def revoke_jti(jti: str, ttl_seconds: int) -> None:
    """Add `jti` to the denylist with the given TTL (seconds). Best-effort.

    Swallows any Redis error (fail-open): if the write is lost during an outage,
    the token stays valid until natural expiry — acceptable per M-1 scope.
    """
    if not jti or ttl_seconds <= 0:
        return
    try:
        _get_client().set(f"{_REVOKED_PREFIX}{jti}", "1", ex=ttl_seconds)
    except redis.RedisError as exc:
        logger.warning("Token revocation write failed (fail-open): %s", exc)


def is_revoked(jti: str) -> bool:
    """True if `jti` is on the denylist. Fail-OPEN: returns False on any Redis error."""
    if not jti:
        return False
    try:
        return _get_client().exists(f"{_REVOKED_PREFIX}{jti}") == 1
    except redis.RedisError as exc:
        logger.warning("Token revocation check failed (fail-open, allowing): %s", exc)
        return False
