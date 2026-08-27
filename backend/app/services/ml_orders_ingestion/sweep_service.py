"""Reconciliation sweep for `ml_orders_ops` (slice 3 of
ml-ventas-fuente-de-verdad).

Primary ingestion path (design D5): windows `search_orders` by
`date_last_updated`, then calls the SAME `upsert_order` a future webhook
accelerator would call, so both paths converge on one idempotent write and
can never double-write (design D5/D8).

Failure model (design D7, restated as the hard constraint this slice must
prove with a test):
- A single row failing inside a window (a mapping error, a stale/no-op
  upsert) is EXPLICITLY recorded and does NOT stall the sweep -- fail-open
  per row.
- The window itself is fail-closed: if the sweep cannot enumerate every
  order in the window (proxy down/5xx/timeout, or an unbisectable
  offset-cap overflow), NOTHING is written for that window and the cursor
  is NOT advanced, so the same window is retried whole on the next run.
- An order ML reports as updated whose own `date_created` falls outside
  the configured rolling window is a HARD EXCLUSION -- never ingested --
  but IS counted, via `ml_ops_divergence.kind='out_of_window_update'`
  (obs #1824 deferred-decision instrumentation, obs #1828 cross-slice
  schema contract).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_orders_ops import MlOpsDivergence, MlOpsSyncCursor
from app.services.ml_orders_ingestion.ingestion_service import UpsertOutcome, upsert_order
from app.services.ml_orders_ingestion.mapper import MappingError, map_order
from app.services.ml_webhook_client import ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

# ML's `/orders/search` offset cap is ~1000; stay comfortably under it so a
# window whose true total sits right at the boundary still bisects instead
# of risking a partial page.
SEARCH_PAGE_SIZE_CAP = 950

# Bounded batch per `get_background_db()` session (design D8): every raw
# order in a batch was already fetched during the (HTTP-only) search phase,
# so no session here is ever held across an HTTP call.
BATCH_SIZE = 200

# Absorbs ML's own update-visibility lag between sweep passes. Free because
# the upsert is idempotent (design D5) -- re-processing the overlap is a
# structural no-op for anything already stored.
CURSOR_OVERLAP = timedelta(minutes=15)

# Below this window width, further bisection is pointless (and would loop
# forever against a window that genuinely never drops below the cap).
MIN_BISECT_SPAN = timedelta(minutes=1)

CURSOR_NAME = "sweep"


class WindowFetchError(Exception):
    """A window's orders could not be fully enumerated. Fail-closed at the
    window level: the caller must NOT write anything for this window and
    must NOT advance the cursor."""


@dataclass
class SweepResult:
    ran: bool
    window_from: Optional[datetime] = None
    window_to: Optional[datetime] = None
    orders_seen: int = 0
    orders_upserted: int = 0
    orders_skipped_stale: int = 0
    orders_mapping_error: int = 0
    orders_out_of_window: int = 0
    error: Optional[str] = None


def _fetch_all_orders(seller_id: int, date_from: datetime, date_to: datetime) -> List[Dict[str, Any]]:
    """Fetches every raw order in `[date_from, date_to)`. Bisects the
    window when ML reports `paging.total > SEARCH_PAGE_SIZE_CAP` rather
    than deepening the offset (design: "the ~1000-result offset cap is
    handled by bisecting the window when paging.total > 950"). Raises
    `WindowFetchError` on ANY failure -- a partial window is worse than no
    window (same fail-closed reasoning as the mapper's fail-closed
    contract, obs #1843)."""
    response = resolve_maybe_async(ml_webhook_client.search_orders(seller_id, date_from, date_to, offset=0))
    if response is None:
        raise WindowFetchError(
            f"search_orders returned no response for window [{date_from.isoformat()}, {date_to.isoformat()})"
        )

    paging = response.get("paging") or {}
    total = paging.get("total")
    if not isinstance(total, int):
        raise WindowFetchError(
            f"search_orders returned no usable paging.total for window [{date_from.isoformat()}, {date_to.isoformat()})"
        )

    if total > SEARCH_PAGE_SIZE_CAP:
        span = date_to - date_from
        if span <= MIN_BISECT_SPAN:
            raise WindowFetchError(
                f"window [{date_from.isoformat()}, {date_to.isoformat()}) cannot be bisected "
                f"further but still reports total={total} > {SEARCH_PAGE_SIZE_CAP}"
            )
        midpoint = date_from + span / 2
        return _fetch_all_orders(seller_id, date_from, midpoint) + _fetch_all_orders(seller_id, midpoint, date_to)

    results: List[Dict[str, Any]] = list(response.get("results") or [])
    offset = len(results)
    while offset < total:
        page = resolve_maybe_async(ml_webhook_client.search_orders(seller_id, date_from, date_to, offset=offset))
        if page is None:
            raise WindowFetchError(
                f"search_orders failed at offset={offset} for window [{date_from.isoformat()}, {date_to.isoformat()})"
            )
        page_results = list(page.get("results") or [])
        if not page_results:
            break
        results.extend(page_results)
        offset += len(page_results)

    return results


def _record_out_of_window(db, order_id: int) -> None:
    """Records (never ingests) an order ML reports as updated whose own
    `date_created` falls outside the rolling window (obs #1824): hard
    exclusion + instrumentation, reusing `ml_ops_divergence` with
    `kind='out_of_window_update'` (obs #1828 cross-slice contract).
    Re-detection updates `detected_at`; the unique `(order_id, kind,
    field)` (NULLS NOT DISTINCT) constraint prevents duplication."""
    existing = (
        db.query(MlOpsDivergence)
        .filter(
            MlOpsDivergence.order_id == order_id,
            MlOpsDivergence.kind == "out_of_window_update",
            MlOpsDivergence.field.is_(None),
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.detected_at = now
    else:
        db.add(MlOpsDivergence(order_id=order_id, kind="out_of_window_update", detected_at=now))


def _process_batch(raw_orders: List[Dict[str, Any]], window_from_floor: datetime, result: SweepResult) -> None:
    """Upserts one bounded batch in its OWN short-lived session. No HTTP
    call happens inside this block -- every raw order was already fetched
    during the (HTTP-only) search phase."""
    with get_background_db() as db:
        for raw_order in raw_orders:
            result.orders_seen += 1
            mapped = map_order(raw_order)
            if isinstance(mapped, MappingError):
                result.orders_mapping_error += 1
                logger.warning("sweep: mapping error for a search result: %s", mapped.reason)
                continue

            if mapped.date_created is not None and mapped.date_created < window_from_floor:
                _record_out_of_window(db, mapped.order_id)
                result.orders_out_of_window += 1
                continue

            outcome = upsert_order(db, raw_order)
            if outcome == UpsertOutcome.OK:
                result.orders_upserted += 1
            elif outcome == UpsertOutcome.SKIPPED_STALE:
                result.orders_skipped_stale += 1
            else:
                result.orders_mapping_error += 1


def _load_cursor(db) -> Optional[MlOpsSyncCursor]:
    return db.query(MlOpsSyncCursor).filter_by(name=CURSOR_NAME).first()


def _tz_aware(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite loses tzinfo on a value round-tripped through the DB (the
    test DB, `tests/conftest.py`'s `sqlite://`) -- a naive value read back
    here is defensively assumed UTC, exactly like the mapper's
    `_parse_tz_aware` (real ML timestamps always carry an offset; this
    only matters for the sqlite test round-trip and any future engine with
    the same gap)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def run_sweep(seller_id: Optional[int] = None, window_days: Optional[int] = None) -> SweepResult:
    """Entry point for the cron sweep (`app/scripts/sync_ml_orders_ops.py`).

    Flag-gated: a complete no-op (zero HTTP calls, zero DB writes/reads)
    while `ML_ORDERS_OPS_ENABLED` is False -- this is proven by a test
    asserting the mocked HTTP client is never called.
    """
    if not settings.ML_ORDERS_OPS_ENABLED:
        return SweepResult(ran=False)

    resolved_seller_id = seller_id if seller_id is not None else settings.ML_USER_ID
    if not resolved_seller_id:
        logger.error("sync_ml_orders_ops: ML_USER_ID not configured, sweep cannot run")
        return SweepResult(ran=False, error="seller_id not configured")

    resolved_window_days = window_days if window_days is not None else settings.ML_ORDERS_OPS_WINDOW_DAYS

    now = datetime.now(timezone.utc)
    window_from_floor = now - timedelta(days=resolved_window_days)

    with get_background_db() as db:
        cursor = _load_cursor(db)
        prior_window_to = _tz_aware(cursor.window_to) if cursor is not None else None

    window_start = (prior_window_to - CURSOR_OVERLAP) if prior_window_to is not None else window_from_floor
    if window_start < window_from_floor:
        window_start = window_from_floor
    window_end = now

    result = SweepResult(ran=True, window_from=window_start, window_to=window_end)

    try:
        raw_orders = _fetch_all_orders(int(resolved_seller_id), window_start, window_end)
    except WindowFetchError as e:
        logger.error("sync_ml_orders_ops: window fetch failed, cursor NOT advanced: %s", e)
        with get_background_db() as db:
            cursor = _load_cursor(db)
            if cursor is None:
                cursor = MlOpsSyncCursor(name=CURSOR_NAME)
                db.add(cursor)
            cursor.state = "error"
            cursor.detail = str(e)[:500]
        result.window_to = prior_window_to
        result.error = str(e)
        return result

    for start in range(0, len(raw_orders), BATCH_SIZE):
        _process_batch(raw_orders[start : start + BATCH_SIZE], window_from_floor, result)

    # The window is fully accounted for -- every row got an explicit
    # outcome (upserted, skipped-stale, mapping-error, or recorded as
    # out-of-window). Only NOW is it safe to checkpoint the cursor.
    with get_background_db() as db:
        cursor = _load_cursor(db)
        if cursor is None:
            cursor = MlOpsSyncCursor(name=CURSOR_NAME)
            db.add(cursor)
        cursor.window_from = window_start
        cursor.window_to = window_end
        cursor.last_success_at = now
        cursor.state = "idle"
        cursor.detail = None

    return result
