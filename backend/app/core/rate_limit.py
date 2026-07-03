"""Login rate limiting — slowapi + Redis, keyed on Cloudflare client IP.

Fail-open by design: if the Redis storage is unreachable the limiter allows the
request through and logs a warning (see design ADR-5). A brute-force window
during a Redis outage is preferable to locking every user out of login.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.exceptions import ErrorCode

logger = logging.getLogger(__name__)

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

    X-Forwarded-For is deliberately NOT consulted (see design ADR-6).
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


# storage_uri falls back to REDIS_URL in prod; tests override to memory://
# via RATE_LIMIT_STORAGE_URI, set before `from app.main import app` (§9).
_storage_uri = settings.RATE_LIMIT_STORAGE_URI or settings.REDIS_URL

limiter = Limiter(
    key_func=client_ip_key,
    storage_uri=_storage_uri,
    strategy="fixed-window",
    swallow_errors=True,  # fail-open primitive (see design §7)
    default_limits=[],  # only the explicitly-decorated login route is limited
    headers_enabled=True,  # required so Retry-After is populated on 429 (§9.1)
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 in the app's centralized error envelope, preserving Retry-After."""
    response = JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": ErrorCode.RATE_LIMITED,
                "message": "Demasiados intentos. Esperá unos minutos e intentá de nuevo.",
            }
        },
    )
    return request.app.state.limiter._inject_headers(response, request.state.view_rate_limit)
