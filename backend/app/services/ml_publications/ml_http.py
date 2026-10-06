"""Synchronous HTTP client for the ML publications store (design D3).

Why not `MercadoLibreAPIClient`: it is async, swallows errors into `None` (the
store must record exact HTTP statuses and error bodies) and is the file other
in-flight work touches. This module only imports its token loader, read-only.

Every call returns an `MlResponse`, never `None`: transport faults, a missing
token or missing credentials become typed outcomes instead of exceptions. The
Authorization header is built per request and never stored, returned or logged.
No DB session is ever held during a call or a pacing sleep (the token loader
opens and closes its own bridge connection).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional

import httpx

from app.core.config import settings
from app.services.ml_api_client import _load_token_from_mlwebhook
from app.services.ml_publications.pacing import DEADLINE, GRANTED, Pacer

logger = logging.getLogger(__name__)

BASE_URL = "https://api.mercadolibre.com"
TOKEN_SAFETY_MARGIN_SECONDS = 60.0
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Outcome classes (also the counter buckets) and the outcomes of calls that were never made.
OUTCOME_NETWORK = "network"
OUTCOME_NOT_CONFIGURED = "not_configured"
OUTCOME_NO_TOKEN = "no_token"

ERROR_TIMEOUT = "timeout"
ERROR_NETWORK = "network"
ERROR_INVALID_JSON = "invalid_json"

_DROPPED_RESPONSE_HEADERS = frozenset({"authorization", "proxy-authorization", "set-cookie", "cookie"})


def outcome_class(status: int) -> str:
    if 200 <= status < 300:
        return "2xx"
    if status == 404:
        return "404"
    if status == 429:
        return "429"
    if 400 <= status < 500:
        return "4xx"
    if status >= 500:
        return "5xx"
    return OUTCOME_NETWORK


@dataclass(frozen=True)
class MlResponse:
    endpoint: str  # endpoint family, for counters
    status: int  # HTTP status; 0 when no response was received (or no call was made)
    body: Any  # parsed JSON (exact integers) or None
    headers: Mapping[str, str]  # lower-cased response headers, credentials removed
    request_started_at: datetime  # UTC, taken just before the request was sent
    received_at: datetime  # UTC, taken when the response (or failure) arrived
    error: Optional[str] = None  # set when there is no usable HTTP answer

    @property
    def outcome(self) -> str:
        if self.error in (OUTCOME_NOT_CONFIGURED, OUTCOME_NO_TOKEN, DEADLINE):
            return self.error
        return outcome_class(self.status)


@dataclass
class Counters:
    """Calls per endpoint family and outcome class, cumulative for the process."""

    _counts: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))

    def inc(self, family: str, outcome: str) -> None:
        self._counts[family][outcome] += 1

    def snapshot(self) -> Dict[str, Dict[str, int]]:
        return {family: dict(outcomes) for family, outcomes in self._counts.items()}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MlHttpClient:
    def __init__(
        self,
        *,
        pacer: Pacer,
        transport: Optional[httpx.BaseTransport] = None,
        token_loader: Optional[Callable[[], Optional[dict]]] = None,
        now: Callable[[], datetime] = _utcnow,
        base_url: str = BASE_URL,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self.pacer = pacer
        self.counters = Counters()
        self._load_token = token_loader or _load_token_from_mlwebhook
        self._now = now
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=timeout, follow_redirects=False)
        self._token: Optional[str] = None
        self._token_expires_epoch = 0.0

    def __enter__(self) -> "MlHttpClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # --- token ------------------------------------------------------------------------

    def _bearer(self, *, refresh: bool = False) -> Optional[str]:
        if (
            not refresh
            and self._token
            and self._now().timestamp() < self._token_expires_epoch - TOKEN_SAFETY_MARGIN_SECONDS
        ):
            return self._token
        data = self._load_token()
        if not data or not data.get("access_token"):
            self._token = None
            return None
        self._token = data["access_token"]
        self._token_expires_epoch = float(data.get("expires_epoch") or 0.0)
        return self._token

    # --- calls ------------------------------------------------------------------------

    def _no_call(self, family: str, error: str) -> MlResponse:
        moment = self._now()
        return MlResponse(family, 0, None, {}, moment, moment, error=error)

    def get(
        self,
        family: str,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
        *,
        deadline: Optional[datetime] = None,
    ) -> MlResponse:
        """One paced GET. Re-reads the token once and retries once on a 401."""
        if not settings.ML_USER_ID or not settings.ML_CLIENT_ID:
            logger.error("ML_USER_ID / ML_CLIENT_ID not set; refusing ML call %s", family)
            return self._no_call(family, OUTCOME_NOT_CONFIGURED)
        token = self._bearer()
        if token is None:
            logger.error("no ML access token available; refusing ML call %s", family)
            return self._no_call(family, OUTCOME_NO_TOKEN)

        response = self._attempt(family, path, params, token, deadline)
        if response.status == 401:
            token = self._bearer(refresh=True)
            if token is None:
                return response
            response = self._attempt(family, path, params, token, deadline)
        return response

    def _attempt(
        self,
        family: str,
        path: str,
        params: Optional[Mapping[str, Any]],
        token: str,
        deadline: Optional[datetime],
    ) -> MlResponse:
        if self.pacer.acquire(family, deadline) != GRANTED:
            return self._no_call(family, DEADLINE)
        started = self._now()
        try:
            raw = self._http.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
        except httpx.TimeoutException:
            return self._finish(MlResponse(family, 0, None, {}, started, self._now(), error=ERROR_TIMEOUT))
        except httpx.TransportError as exc:
            logger.warning("ML transport error on %s: %s", family, type(exc).__name__)
            return self._finish(MlResponse(family, 0, None, {}, started, self._now(), error=ERROR_NETWORK))
        received = self._now()
        headers = {k.lower(): v for k, v in raw.headers.items() if k.lower() not in _DROPPED_RESPONSE_HEADERS}
        body: Any = None
        error: Optional[str] = None
        if raw.content:
            try:
                body = json.loads(raw.content)
            except ValueError:
                error = ERROR_INVALID_JSON if 200 <= raw.status_code < 300 else None
        return self._finish(MlResponse(family, raw.status_code, body, headers, started, received, error=error))

    def _finish(self, response: MlResponse) -> MlResponse:
        self.counters.inc(response.endpoint, response.outcome)
        if response.status == 429:
            self.pacer.on_rate_limited(response.headers.get("retry-after"))
        elif 200 <= response.status < 300:
            self.pacer.on_success()
        return response
