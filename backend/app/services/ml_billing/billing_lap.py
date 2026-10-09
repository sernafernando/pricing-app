"""The billing lap: the sweep as resumable ticks of ONE proxy request (ml-billing-balance D12, BS-4, BS-8).

The cron ran one blocking pass over the OPEN period. The worker instead walks a
LAP over every period ML lists (the open one plus the 11 closed ones of the
first `monthly/periods` page), and each tick makes exactly one request, so the
proxy's 1 call/15 s throttle and ML's hard 5 requests/minute per account hold by
construction and the worker is never blocked for minutes.

`state` is plain JSON that the handler keeps in `worker_job_state.detail`; it IS
the cursor (the billing lap has no ML-side ledger). Deleting it loses no data,
only the position: the next run builds a new lap and the upserts are idempotent.

    {complete, last_request_at, retry_at, failures,
     lap: {id, started_at, index, units: [{period_key, document_type, kind,
           state, from_id, total, pages}]} | None, last_lap}

A lap has, per period, BILL details, BILL documents, CREDIT_NOTE details and
CREDIT_NOTE documents. Order: the open period, then the closed ones newest first.

Failures: a 429, a timeout or a 5xx keeps the cursor and sets
`retry_at = now + min(60 s * 2^(failures-1), 15 min)`; the fifth in a row on one
unit fails the unit and the lap moves on (the next lap retries it). Any other
4xx fails the unit at once: the poison-row engine (`poison_rows`) is not wired
here yet, so a bare 400 halts that period's details exactly as the cron did.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from app.services.ml_billing.billing_sweep_service import (
    BILLING_GROUP,
    DOCUMENT_TYPES,
    PAGE_LIMIT,
    _cursor_value,
    _highest_detail_id,
    _page_cap,
    persist_details_page,
    persist_documents,
)
from app.services.ml_webhook_client import ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

SPACING = timedelta(seconds=15)  # the proxy answers 429 to anything faster
FAILURE_LIMIT = 5
BACKOFF_BASE = timedelta(seconds=60)
BACKOFF_CAP = timedelta(minutes=15)
OPEN = "OPEN"


def backoff(failures: int) -> timedelta:
    return min(BACKOFF_BASE * 2 ** max(failures - 1, 0), BACKOFF_CAP)


def _when(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _units(periods: list[dict]) -> list[dict]:
    keys = [(p["key"], p.get("period_status")) for p in periods if isinstance(p, dict) and p.get("key")]
    ordered = [k for k, status in keys if status == OPEN] + sorted((k for k, s in keys if s != OPEN), reverse=True)
    return [
        {
            "period_key": key,
            "document_type": document_type,
            "kind": kind,
            "state": "pending",
            "from_id": 0,
            "total": None,
            "pages": 0,
        }
        for key in ordered
        for document_type in DOCUMENT_TYPES
        for kind in ("details", "documents")
    ]


def run_billing_tick(db, state: dict, now: datetime) -> dict:
    """One tick: at most ONE proxy request. Returns the new state; the caller commits."""
    last, retry = _when(state.get("last_request_at")), _when(state.get("retry_at"))
    if (last is not None and now - last < SPACING) or (retry is not None and now < retry):
        return state
    if state.get("complete", True) or not state.get("lap"):
        return _start_lap(state, now)
    return _step(db, state, now)


def _start_lap(state: dict, now: datetime) -> dict:
    state["last_request_at"] = now.isoformat()
    payload = resolve_maybe_async(ml_webhook_client.get_billing_periods(BILLING_GROUP))
    periods = (payload or {}).get("results")
    if not isinstance(periods, list) or not periods:
        return _transport_failure(state, None, now)
    state.update(complete=False, failures=0, retry_at=None)
    state["lap"] = {
        "id": now.isoformat(),
        "started_at": now.isoformat(),
        "index": 0,
        "units": _units(periods),
    }
    return _close_lap_if_done(state, now)


def _step(db, state: dict, now: datetime) -> dict:
    unit = state["lap"]["units"][state["lap"]["index"]]
    state["last_request_at"] = now.isoformat()
    if unit["kind"] == "details":
        return _details(db, state, unit, now)
    return _documents(db, state, unit, now)


def _details(db, state: dict, unit: dict, now: datetime) -> dict:
    period, document_type = unit["period_key"], unit["document_type"]
    fetch = resolve_maybe_async(
        ml_webhook_client.fetch_billing_details(period, BILLING_GROUP, document_type, PAGE_LIMIT, unit["from_id"])
    )
    if not fetch.ok:
        if fetch.status is not None and fetch.status != 429 and 400 <= fetch.status < 500:
            logger.error("ml_billing lap: %s %s details rejected (HTTP %s)", period, document_type, fetch.status)
            return _finish(state, unit, "failed", now)
        return _transport_failure(state, unit, now)
    page = fetch.body
    if unit["total"] is None and isinstance(page.get("total"), int):
        unit["total"] = page["total"]  # the FIRST page's total is the period's size (BS-1)
    rows = list(page.get("results") or [])
    persist_details_page(db, rows, period, document_type)
    if not rows:
        return _finish(state, unit, "done", now)
    cursor = page.get("last_id")
    if cursor is None:
        cursor = _highest_detail_id(rows)
    advanced = _cursor_value(cursor)
    unit["pages"] += 1
    if advanced is None or advanced <= _cursor_value(unit["from_id"]):
        logger.warning(
            "ml_billing lap: cursor did not advance (%s %s from_id=%s)", period, document_type, unit["from_id"]
        )
        return _finish(state, unit, "failed", now)
    if unit["total"] is not None and unit["pages"] >= _page_cap(unit["total"]):
        logger.warning("ml_billing lap: %s %s exceeded the expected pages", period, document_type)
        return _finish(state, unit, "failed", now)
    unit["from_id"] = cursor
    state["failures"], state["retry_at"] = 0, None
    return state


def _documents(db, state: dict, unit: dict, now: datetime) -> dict:
    period, document_type = unit["period_key"], unit["document_type"]
    documents = resolve_maybe_async(ml_webhook_client.get_billing_documents(period, BILLING_GROUP, document_type))
    if documents is None:
        return _transport_failure(state, unit, now)
    persist_documents(db, documents, period, BILLING_GROUP, document_type)
    return _finish(state, unit, "done", now)


def _transport_failure(state: dict, unit: Optional[dict], now: datetime) -> dict:
    state["complete"] = False  # the 15 s catch-up keeps retrying, gated by `retry_at`
    state["failures"] = state.get("failures", 0) + 1
    if unit is not None and state["failures"] >= FAILURE_LIMIT:
        return _finish(state, unit, "failed", now)
    state["retry_at"] = (now + backoff(state["failures"])).isoformat()
    return state


def _finish(state: dict, unit: dict, outcome: str, now: datetime) -> dict:
    unit["state"] = outcome
    state["lap"]["index"] += 1
    state["failures"], state["retry_at"] = 0, None
    return _close_lap_if_done(state, now)


def _close_lap_if_done(state: dict, now: datetime) -> dict:
    lap: Any = state["lap"]
    if lap["index"] >= len(lap["units"]):
        failed = [
            {k: u[k] for k in ("period_key", "document_type", "kind")} for u in lap["units"] if u["state"] == "failed"
        ]
        state["last_lap"] = {"started_at": lap["started_at"], "finished_at": now.isoformat(), "failed": failed}
        state["complete"], state["lap"] = True, None
    return state
