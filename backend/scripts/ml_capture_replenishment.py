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

    # Read the Full quantity straight from the stored `raw->'locations'` (the P3 typed columns may not
    # be deployed yet where this runs). `meli_facility` is ML's Full warehouse.
    full_qty = (
        "COALESCE((SELECT SUM((loc->>'quantity')::numeric) FROM jsonb_array_elements("
        "CASE WHEN jsonb_typeof(raw->'locations') = 'array' THEN raw->'locations' ELSE '[]'::jsonb END) loc "
        "WHERE loc->>'type' = 'meli_facility'), 0)"
    )
    db = SessionLocal()
    try:
        full = [
            r[0]
            for r in db.execute(
                text(
                    f"SELECT user_product_id FROM ml_user_product_stock WHERE {full_qty} > 0 "
                    f"ORDER BY {full_qty} DESC, user_product_id LIMIT :n"
                ),
                {"n": FULL_LIMIT},
            )
        ]
        non_full = [
            r[0]
            for r in db.execute(
                text(
                    f"SELECT user_product_id FROM ml_user_product_stock "
                    f"WHERE jsonb_typeof(raw->'locations') = 'array' AND {full_qty} = 0 "
                    "ORDER BY user_product_id LIMIT :n"
                ),
                {"n": NON_FULL_LIMIT},
            )
        ]
    finally:
        db.close()
    return build_targets(full, non_full)


def _items_from_recent_sales() -> Dict[str, List[str]]:
    """Fallback when no stock with locations is stored yet: the MLAs of recent sales, split by the
    shipment's logistic type (`fulfillment` = Full). Read-only."""
    from sqlalchemy import text

    from app.core.database import SessionLocal

    sql = (
        "SELECT oi.item_id FROM ml_order_items_ops oi "
        "JOIN ml_orders_ops o ON o.order_id = oi.order_id "
        "JOIN ml_shipments_ops s ON s.shipment_id = o.shipping_id "
        "WHERE s.logistic_type {op} 'fulfillment' AND oi.item_id IS NOT NULL "
        "GROUP BY oi.item_id ORDER BY max(o.date_created) DESC LIMIT :n"
    )
    db = SessionLocal()
    try:
        full = [r[0] for r in db.execute(text(sql.format(op="=")), {"n": 20})]
        non_full = [r[0] for r in db.execute(text(sql.format(op="<>")), {"n": 10})]
    finally:
        db.close()
    return {"full": full, "non_full": non_full}


def extract_user_product_ids(
    bodies: Sequence[Mapping[str, Any]], limit: int = 1_000, found: Optional[List[str]] = None
) -> List[str]:
    """MLAUs of item bodies: the item-level `user_product_id`, else each variation's. Appends to `found`."""
    found = [] if found is None else found
    for body in bodies:
        candidates = [body.get("user_product_id")] + [v.get("user_product_id") for v in body.get("variations") or []]
        for upid in candidates:
            if upid and upid not in found:
                found.append(upid)
            if len(found) >= limit:
                return found
    return found


def _user_products_of(client: httpx.Client, token: str, item_ids: Sequence[str], limit: int) -> List[str]:
    """User product ids (MLAU) of the given MLAs via `/items/bulk` (GET, full body). The id lives on the
    item (`user_product_id`) or, for items with variations, on each variation."""
    found: List[str] = []
    for i in range(0, len(item_ids), 20):
        response = client.get(
            "/items/bulk",
            params={"ids": ",".join(item_ids[i : i + 20])},
            headers={"Authorization": f"Bearer {token}"},
        )
        time.sleep(MIN_INTERVAL_SECONDS)
        if response.status_code != 200:
            print(f"  /items/bulk -> {response.status_code}")
            continue
        bodies = [e.get("body") for e in response.json() if isinstance(e, dict) and isinstance(e.get("body"), dict)]
        with_variations = sum(1 for b in bodies if b.get("variations"))
        item_level = sum(1 for b in bodies if b.get("user_product_id"))
        print(
            f"  /items/bulk: {len(bodies)} bodies, {item_level} with item user_product_id, {with_variations} with variations"
        )
        extract_user_product_ids(bodies, limit=limit, found=found)
        if len(found) >= limit:
            return found
    return found


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
        targets: Optional[List[Target]] = _select_targets()
    except NothingToCapture as exc:
        print(f"No stored Full stock ({exc}); falling back to recent sales by logistic type.")
        targets = None

    with httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False) as client:
        if targets is None:
            items = _items_from_recent_sales()
            print(
                f"  recent sales: {len(items['full'])} Full MLAs, {len(items['non_full'])} other MLAs; e.g. {items['full'][:3]}"
            )
            full = _user_products_of(client, token_data["access_token"], items["full"], FULL_LIMIT)
            non_full = [
                u
                for u in _user_products_of(client, token_data["access_token"], items["non_full"], NON_FULL_LIMIT + 3)
                if u not in full
            ][:NON_FULL_LIMIT]
            if not full:
                print("Nothing to capture: no Full user product found from recent sales either")
                return 3
            targets = build_targets(full, non_full)
        capture = ReplenishmentCapture(client=client, token=token_data["access_token"], caller_id=str(caller_id))
        records = run_captures(capture, targets)

    path = write_output(records)
    print("\n".join(summary_lines(records)))
    print(f"Output: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
