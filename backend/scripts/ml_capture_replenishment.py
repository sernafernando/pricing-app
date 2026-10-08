"""Read-only capture of the ML FBM replenishment endpoint (pubml P4a.T1).

    GET /marketplace/fbm/user-products/{MLAU}/replenishment?country=AR

Why it exists: the reference app (meli-full-report) reaches this endpoint through ml-webhook,
which injects `x-caller-id` / `x-caller-siteId`. The publications store calls api.mercadolibre.com
directly, so before writing a parser we need the REAL responses and the answer to "does ML require
the caller headers on a direct call?". A hand-written fixture would only be our assumption.

What it captures (each case is one MLAU):
  full_N               Full user products (full_quantity > 0), WITH caller headers (200, maybe 206)
  non_full_N           user products that are not Full, WITH caller headers (expected 404)
  full_1_no_caller     the first Full MLAU WITHOUT caller headers
  non_full_1_no_caller the first non-Full MLAU WITHOUT caller headers

Safety envelope: GET only, one call at a time paced >= 0.7 s, backoff on 429, the token is read
the same way the store reads it (`ml_tokens` in the ml-webhook DB) and is never printed or
written: the output redacts it even if ML echoes it back. Only the `date` and `x-content-missing`
response headers are kept.

Run from /var/www/html/pricing-app/backend:

    venv/bin/python /tmp/ml_capture_replenishment.py

Output: /tmp/replenishment_capture_<timestamp>.json plus one summary line per case on stdout.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

import httpx

BASE_URL = "https://api.mercadolibre.com"
PATH_TEMPLATE = "/marketplace/fbm/user-products/{mlau}/replenishment"
COUNTRY = "AR"
SITE_ID = "MLA"

MIN_INTERVAL_SECONDS = 0.7
MAX_429_RETRIES = 3
DEFAULT_429_WAIT_SECONDS = 5.0
MAX_RETRY_AFTER_SECONDS = 120.0

ALLOWED_RESPONSE_HEADERS = ("date", "x-content-missing")
SENSITIVE_KEYS = frozenset(
    {"authorization", "proxy-authorization", "access_token", "refresh_token", "token", "client_secret", "cookie"}
)
REDACTED = "<redacted>"

FULL_LIMIT = 5
NON_FULL_LIMIT = 2
OUTPUT_DIR = Path("/tmp")


class NothingToCapture(Exception):
    """No Full user product was found: the capture would not answer anything."""


@dataclass(frozen=True)
class Target:
    case: str
    mlau: str
    with_caller: bool


# --- pure helpers ------------------------------------------------------------------------------


def filter_response_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    """Whitelist: everything else (cookies, request ids, anything credential-like) is dropped."""
    lowered = {str(k).lower(): v for k, v in headers.items()}
    return {name: lowered[name] for name in ALLOWED_RESPONSE_HEADERS if name in lowered}


def redact(value: Any, secrets: Sequence[str] = ()) -> Any:
    """Mask sensitive keys and any literal occurrence of a known secret, recursively."""
    if isinstance(value, dict):
        return {k: (REDACTED if str(k).lower() in SENSITIVE_KEYS else redact(v, secrets)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret and secret in value:
                value = value.replace(secret, REDACTED)
        return value
    return value


def build_targets(full: Sequence[str], non_full: Sequence[str]) -> List[Target]:
    if not full:
        raise NothingToCapture("no Full user product (full_quantity > 0) found")
    targets = [Target(f"full_{i}", mlau, True) for i, mlau in enumerate(full, start=1)]
    targets += [Target(f"non_full_{i}", mlau, True) for i, mlau in enumerate(non_full, start=1)]
    targets.append(Target("full_1_no_caller", full[0], False))
    if non_full:
        targets.append(Target("non_full_1_no_caller", non_full[0], False))
    return targets


def summary_lines(records: Iterable[Mapping[str, Any]]) -> List[str]:
    lines = []
    for r in records:
        partial = r["response_headers"].get("x-content-missing")
        extra = f" x-content-missing={partial}" if partial else ""
        lines.append(
            f"{r['case']:<22} {r['mlau']:<18} status={r['status']} attempts={r['attempts']} "
            f"caller_headers={'yes' if r['caller_headers_sent'] else 'no'}{extra}"
        )
    return lines


def write_output(
    records: Sequence[Mapping[str, Any]], *, directory: Path = OUTPUT_DIR, stamp: Optional[str] = None
) -> Path:
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = directory / f"replenishment_capture_{stamp}.json"
    payload = {"captured_at": stamp, "endpoint": f"{PATH_TEMPLATE}?country={COUNTRY}", "cases": list(records)}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


# --- the capture -------------------------------------------------------------------------------


class ReplenishmentCapture:
    """Issues paced GETs. It never builds a request with another verb and never logs the token."""

    def __init__(
        self,
        *,
        client: httpx.Client,
        token: str,
        caller_id: str,
        site_id: str = SITE_ID,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._token = token
        self._caller_id = caller_id
        self._site_id = site_id
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_call: Optional[float] = None

    def _pace(self) -> None:
        if self._last_call is not None:
            wait = MIN_INTERVAL_SECONDS - (self._monotonic() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._monotonic()

    def _headers(self, with_caller: bool) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        if with_caller:
            headers["x-caller-id"] = self._caller_id
            headers["x-caller-siteId"] = self._site_id
        return headers

    @staticmethod
    def _retry_wait(response: httpx.Response) -> float:
        try:
            wait = float(response.headers.get("retry-after", "0"))
        except ValueError:
            wait = 0.0
        if wait <= 0:
            wait = DEFAULT_429_WAIT_SECONDS
        return min(wait, MAX_RETRY_AFTER_SECONDS)

    def capture(self, case: str, mlau: str, *, with_caller: bool) -> Dict[str, Any]:
        path = PATH_TEMPLATE.format(mlau=mlau)
        secrets = [self._token]
        attempts = 0
        response: Optional[httpx.Response] = None
        error: Optional[str] = None
        while True:
            self._pace()
            attempts += 1
            try:
                response = self._client.get(path, params={"country": COUNTRY}, headers=self._headers(with_caller))
            except httpx.HTTPError as exc:
                response, error = None, f"{type(exc).__name__}: {exc}"
                break
            if response.status_code == 429 and attempts <= MAX_429_RETRIES:
                self._sleep(self._retry_wait(response))
                continue
            break

        body: Any = None
        headers: Dict[str, str] = {}
        status = 0
        if response is not None:
            status = response.status_code
            headers = filter_response_headers(response.headers)
            try:
                body = response.json() if response.content else None
            except ValueError:
                body = {"_non_json_body": response.text[:2000]}
        record = {
            "case": case,
            "mlau": mlau,
            "request": f"GET {path}?country={COUNTRY}",
            "caller_headers_sent": with_caller,
            "attempts": attempts,
            "status": status,
            "response_headers": headers,
            "body": body,
            "error": error,
        }
        return redact(record, secrets)


def run_captures(capture: ReplenishmentCapture, targets: Sequence[Target]) -> List[Dict[str, Any]]:
    return [capture.capture(t.case, t.mlau, with_caller=t.with_caller) for t in targets]


# --- entry point (DB + token; kept out of the pure helpers) ------------------------------------


def _select_targets() -> List[Target]:
    from sqlalchemy import text

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        full = [
            r[0]
            for r in db.execute(
                text(
                    "SELECT user_product_id FROM ml_user_product_stock "
                    "WHERE full_quantity > 0 ORDER BY full_quantity DESC, user_product_id LIMIT :n"
                ),
                {"n": FULL_LIMIT},
            )
        ]
        if not full:  # P3 columns not filled yet: fall back to the items' logistic type
            full = [
                r[0]
                for r in db.execute(
                    text(
                        "SELECT DISTINCT user_product_id FROM ml_items "
                        "WHERE logistic_type = 'fulfillment' AND user_product_id IS NOT NULL "
                        "ORDER BY user_product_id LIMIT :n"
                    ),
                    {"n": FULL_LIMIT},
                )
            ]
        non_full = [
            r[0]
            for r in db.execute(
                text(
                    "SELECT DISTINCT i.user_product_id FROM ml_items i "
                    "WHERE i.user_product_id IS NOT NULL "
                    "AND COALESCE(i.logistic_type, '') <> 'fulfillment' "
                    "AND NOT EXISTS (SELECT 1 FROM ml_user_product_stock s "
                    "                WHERE s.user_product_id = i.user_product_id AND s.full_quantity > 0) "
                    "AND NOT EXISTS (SELECT 1 FROM ml_items f "
                    "                WHERE f.user_product_id = i.user_product_id AND f.logistic_type = 'fulfillment') "
                    "ORDER BY i.user_product_id LIMIT :n"
                ),
                {"n": NON_FULL_LIMIT},
            )
        ]
    finally:
        db.close()
    return build_targets(full, non_full)


def main() -> int:
    sys.path.insert(0, os.getcwd())
    from app.core.config import settings
    from app.services.ml_api_client import _load_token_from_mlwebhook

    caller_id = settings.ML_USER_ID
    if not caller_id:
        print("ML_USER_ID is not configured; nothing was called.")
        return 2
    token_data = _load_token_from_mlwebhook()
    if not token_data or not token_data.get("access_token"):
        print("No ML access token available in the ml-webhook DB; nothing was called.")
        return 2

    try:
        targets = _select_targets()
    except NothingToCapture as exc:
        print(f"Nothing to capture: {exc}")
        return 3

    with httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False) as client:
        capture = ReplenishmentCapture(client=client, token=token_data["access_token"], caller_id=str(caller_id))
        records = run_captures(capture, targets)

    path = write_output(records)
    print("\n".join(summary_lines(records)))
    print(f"Output: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
