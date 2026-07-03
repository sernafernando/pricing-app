"""Login rate limiting — slowapi + Redis, keyed on Cloudflare client IP.

Fail-open by design: if the Redis storage is unreachable the limiter allows the
request through and logs a warning (see
openspec/changes/security-quick-wins/design.md, ADR-5). A brute-force window
during a Redis outage is preferable to locking every user out of login.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from limits.util import parse as parse_rate_limit
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.exceptions import ErrorCode

logger = logging.getLogger(__name__)

# Aggressive socket timeouts passed straight through to redis-py (slowapi
# forwards `storage_options` to `limits.storage.storage_from_string`, which
# forwards remaining kwargs to `redis.from_url(...)`). Without this, an
# unresponsive/black-holed Redis blocks a threadpool worker for the OS default
# timeout (can be minutes) BEFORE `swallow_errors` gets a chance to fail open —
# turning fail-open into a de-facto fail-closed under exactly the outage
# scenario it's meant to protect against. See
# openspec/changes/security-quick-wins/design.md, §7.
# `memory://` storage (used in tests) silently ignores unknown kwargs, so this
# is safe to pass unconditionally regardless of the active storage backend.
REDIS_STORAGE_OPTIONS = {
    "socket_connect_timeout": 0.25,
    "socket_timeout": 0.25,
}

# Surface slowapi's own warning log (emitted when swallow_errors catches a
# storage failure) under the project's logging config.
logging.getLogger("slowapi").setLevel(logging.WARNING)


def client_ip_key(request: Request) -> str:
    """Rate-limit key: real client IP.

    Priority:
      1. CF-Connecting-IP  — set by Cloudflare on every tunneled request and
         trustworthy because the origin is ONLY reachable through the tunnel.
      2. request.client.host — direct TCP peer, used only in local dev / direct
         hits where no Cloudflare header exists. Unspoofable (it is the socket
         peer), unlike X-Forwarded-For.

    X-Forwarded-For is deliberately NOT consulted (see
    openspec/changes/security-quick-wins/design.md, ADR-6).
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


# storage_uri falls back to REDIS_URL in prod; tests override to memory://
# via RATE_LIMIT_STORAGE_URI, set before `from app.main import app` (see
# openspec/changes/security-quick-wins/design.md, §9).
_storage_uri = settings.RATE_LIMIT_STORAGE_URI or settings.REDIS_URL

limiter = Limiter(
    key_func=client_ip_key,
    storage_uri=_storage_uri,
    storage_options=REDIS_STORAGE_OPTIONS,
    strategy="fixed-window",
    swallow_errors=True,  # fail-open primitive (see design.md, §7)
    default_limits=[],  # only the explicitly-decorated login route is limited
    # headers_enabled=False: we build Retry-After ourselves in the 429 handler
    # below from the configured window, avoiding slowapi's success-path
    # get_window_stats() call (a second Redis round-trip on every login).
    headers_enabled=False,
)

# Retry-After window, in seconds, derived once from the same rate string used
# to decorate the login route (e.g. "10/minute" -> 60).
_LOGIN_RATE_LIMIT_WINDOW_SECONDS = parse_rate_limit(settings.LOGIN_RATE_LIMIT).get_expiry()


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 in the app's centralized error envelope, with an explicit Retry-After.

    headers_enabled=False on the Limiter means slowapi does not inject
    Retry-After itself, so it's set here directly from the configured login
    rate-limit window — no dependency on slowapi's private `_inject_headers`.
    """
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": ErrorCode.RATE_LIMITED,
                "message": "Demasiados intentos. Esperá unos minutos e intentá de nuevo.",
            }
        },
        headers={"Retry-After": str(_LOGIN_RATE_LIMIT_WINDOW_SECONDS)},
    )
