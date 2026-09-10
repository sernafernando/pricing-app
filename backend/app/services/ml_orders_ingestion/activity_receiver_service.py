"""Event-driven drain of the ml-webhook activity bridge
(ml-activity-receiver, slice 3 of 4).

The sweep (`sweep_service.run_sweep`) is a WINDOWED poll: it asks ML
`search_orders` for everything `date_last_updated` inside a rolling
window, on its own cadence. This module is the opposite shape: it asks
the bridge's `/api/ml/activity` feed for events SINCE an opaque cursor,
and is meant to be triggered by a lightweight ping (the router endpoint
in this same slice) rather than a fixed schedule. Slice 4 (deliberately
separate, not part of this slice) demotes the sweep's cadence to an
hourly audit once this path is observed draining successfully in
production -- until then the sweep's cadence is UNCHANGED and this path
is a pure addition, not a replacement.

Reuse, not reinvention (design D1-D5): this module calls the exact same
`process_batch` the sweep uses to upsert orders/shipments/payments, and
reuses the sweep's own run-lock/cursor helpers
(`try_acquire_run_lock`/`release_lock_as_idle`/`release_lock_as_error`/
`load_cursor`/`ensure_cursor_row`) under a DISTINCT `cursor_name`
(`ml_activity`), so this drain and the sweep can run concurrently without
ever racing the same row -- exactly the same reasoning that already lets
the sweep and `backfill_payments_costs_service` coexist.

Why not `search_orders` (design D1, rejected alternative): an activity
event carries only an `order_id` (obs #2008), not a `date_last_updated`
window. Feeding those ids into `search_orders`'s window semantics would
recreate a second, ad hoc sweep keyed on whatever window happens to
contain "now" -- and could pull in orders no event ever mentioned,
defeating the point of an event-driven path. `get_order(order_id)` is the
one call shaped like the actual question: "what does ML say about THIS
order right now".

Per-order dedup is PER PASS, not per page (design D2): a single ML
"pack" can fan out into several events across one or more bridge pages,
each carrying the SAME `order_id` -- fetching the order again for every
one of those would multiply the HTTP cost by however many items happen
to share a pack, for zero additional information. `_seen_this_pass`
below is the pass-wide cache that makes a repeated `order_id` free
everywhere except the FIRST time it is seen in this drain invocation,
whether that first sighting was on this page or an earlier one.

Cursor-advance discipline (design D3/D4, the bookkeeping this slice
exists to prove):
  1. `activity_cursor` only ever advances to a page's `next_cursor`
     AFTER `process_batch` has opened, written, and COMMITTED its own
     short-lived session for every order this drain resolved from that
     page -- in a SEPARATE `get_background_db()` block, mirroring the
     sweep's own checkpoint-after-flush ordering.
  2. A page whose order resolution the per-pass budget or the deadline
     cut short is NOT advanced past -- the SAME `since` cursor is kept,
     so the identical page (same events, same order ids still owed a
     fetch) is re-asked next run instead of silently skipping whatever
     this pass could not reach. That pass is also not stamped complete
     (`release_lock_as_idle(complete=False)`), which is the sweep's own
     truncation contract, reused unchanged.
  3. HTTP 400 (`ActivityCursorRejected`) is deliberately left UNCAUGHT
     inside the loop: it propagates to `release_lock_as_error`, which
     marks the cursor row `state='error'` with the bridge's own message
     and leaves `activity_cursor` byte-identical -- an invalid cursor
     is a visible, operator-actionable failure, never a silent reset
     back to "never drained".

`orders_resolved` (a real `get_order` payload came back) is counted
SEPARATELY from `orders_not_attempted` (the per-pass budget or the
deadline was hit before this order's own fetch even started) and from
`orders_unresolved` (the fetch was attempted and ML returned nothing --
a genuine miss, e.g. a 404/timeout). Collapsing "never asked" into
"failed" was a real, already-shipped bug on this exact codepath
(commit `9cc60ef7`, `backfill_payments_costs_service.py`): a shipment
the budget never reached was charged a give-up attempt as if ML had
actually been asked and said no. This module keeps the same three-way
split from the start.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_orders_ops import MlOpsDivergence
from app.services.ml_orders_ingestion.sweep_service import (
    BATCH_SIZE,
    CURSOR_NAME as SWEEP_CURSOR_NAME,
    MAX_COST_FETCHES_PER_PASS,
    MAX_PAYMENT_FETCHES_PER_PASS,
    MAX_WINDOW_FETCHES_PER_PASS,
    STALE_LOCK_TIMEOUT,
    SweepResult,
    _pass_deadline_reached,
    ensure_cursor_row,
    load_cursor,
    process_batch,
    release_lock_as_error,
    release_lock_as_idle,
    try_acquire_run_lock,
)
from app.services.ml_webhook_client import ActivityCursorRejected, ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

CURSOR_NAME = "ml_activity"

# Never reused by anything else: guards against a future refactor
# accidentally pointing this drain at the sweep's own cursor row (same
# discipline as `backfill_payments_costs_service.py`'s own guard). A
# plain `assert` is stripped under `python -O`; fail loudly and
# unconditionally instead.
if CURSOR_NAME == SWEEP_CURSOR_NAME:
    raise RuntimeError("activity_receiver_service.CURSOR_NAME must not collide with the sweep's own cursor name")

# A SEPARATE budget from the sweep's three (`MAX_WINDOW_FETCHES_PER_PASS`,
# `MAX_COST_FETCHES_PER_PASS`, `MAX_PAYMENT_FETCHES_PER_PASS`) -- reusing
# any one of them would reproduce the exact starvation those budgets were
# split apart to prevent: a burst of activity events resolving orders
# would compete for the same shared ceiling as page-walking or cost/
# payment sync on a concurrently-running sweep pass, and one path would
# starve the other for no reason. This budget covers ONLY the
# `get_order` fetches this drain performs to resolve an event's order id
# into a payload `process_batch` can upsert.
MAX_ACTIVITY_ORDER_FETCHES_PER_PASS = 500

FLAG_OFF_REASON = "ML_ORDERS_OPS_ENABLED is False"


@dataclass
class ActivityDrainResult:
    ran: bool
    pages_walked: int = 0
    events_seen: int = 0
    events_without_order_id: int = 0
    orders_resolved: int = 0
    orders_unresolved: int = 0
    orders_not_attempted: int = 0
    # Everything below comes straight from `process_batch`'s own counters.
    # They are copied out on purpose: this result used to report only that
    # `get_order` had answered, and threw away what happened NEXT. When a
    # field-name mismatch made EVERY resolved order fail to map, the drain
    # still logged "drain complete ... resolved=N" and nothing anywhere
    # said that N orders had been discarded. A pass that ingests nothing
    # must not read like a pass that worked.
    orders_upserted: int = 0
    orders_skipped_stale: int = 0
    orders_mapping_error: int = 0
    orders_out_of_window: int = 0
    budget_exhausted: bool = False
    error: Optional[str] = None


def _collect_new_order_ids(events: List[Dict[str, Any]], seen_this_pass: Dict[int, bool]) -> tuple[List[int], int]:
    """Returns (new_order_ids_in_page_order, events_without_order_id),
    where `new_order_ids` is insertion-ordered and excludes any id
    already resolved (successfully or not) earlier in THIS pass -- see
    module docstring on per-pass dedup."""
    new_ids: Dict[int, None] = {}
    without_order_id = 0
    for event in events:
        order_id = event.get("order_id")
        if order_id is None:
            without_order_id += 1
            continue
        if order_id in seen_this_pass:
            continue
        new_ids.setdefault(order_id, None)
    return list(new_ids.keys()), without_order_id


UNRESOLVED_FIELD = "activity_unresolved"


def _record_unresolved_order(db, order_id: int) -> None:
    """A `get_order` that came back empty is a TRANSIENT answer -- the
    client's own docstring counts timeouts, network errors and 5xx as
    `None` -- so it must not vanish once the cursor moves past its page.

    Why the debt is recorded instead of holding the cursor: refusing to
    advance while ANY order is unresolved wedges the whole feed behind a
    single permanently-dead order, which is precisely the bug fixed in
    `9cc60ef7` for the payments/costs backfill (a row that never settled
    blocked every candidate behind it). Recording the debt keeps the
    stream moving AND keeps the miss visible: the row is operator-facing
    in the divergence dashboard, and the audit sweep re-ingests the order
    on its next window pass. Deduped by the `(order_id, kind, field)`
    unique constraint, so a repeated miss refreshes `detected_at`.
    """
    existing = (
        db.query(MlOpsDivergence)
        .filter(
            MlOpsDivergence.order_id == order_id,
            MlOpsDivergence.kind == "unknown",
            MlOpsDivergence.field == UNRESOLVED_FIELD,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.detected_at = now
    else:
        db.add(MlOpsDivergence(order_id=order_id, kind="unknown", field=UNRESOLVED_FIELD, detected_at=now))


def _clear_unresolved_orders(db, order_ids) -> None:
    """A later pass DID resolve these orders, so the recorded debt is
    settled and must not linger as a permanent false alarm -- the same
    lesson as clearing the cost-sync give-up counter on success."""
    if not order_ids:
        return
    db.query(MlOpsDivergence).filter(
        MlOpsDivergence.order_id.in_(list(order_ids)),
        MlOpsDivergence.kind == "unknown",
        MlOpsDivergence.field == UNRESOLVED_FIELD,
    ).delete(synchronize_session=False)


def drain_activity() -> ActivityDrainResult:
    """Entry point for the ping endpoint's background task (this same
    slice). Flag-gated exactly like the sweep/backfill: a complete no-op
    (zero HTTP calls, zero DB writes/reads beyond the flag check) while
    `ML_ORDERS_OPS_ENABLED` is False, and `error` stays `None` in that
    case -- the flag being off is an expected outcome, not a failure."""
    if not settings.ML_ORDERS_OPS_ENABLED:
        logger.info("activity_receiver: did not run (%s)", FLAG_OFF_REASON)
        return ActivityDrainResult(ran=False)

    now = datetime.now(timezone.utc)
    # Identical to `run_sweep`'s own floor (`sweep_service.py:1135`):
    # passing `now()` here would make every real order look out-of-window
    # and fabricate one `ml_ops_divergence` row per event `process_batch`
    # touches.
    window_from_floor = now - timedelta(days=settings.ML_ORDERS_OPS_WINDOW_DAYS)

    with get_background_db() as db:
        acquired = try_acquire_run_lock(db, now, cursor_name=CURSOR_NAME, stale_timeout=STALE_LOCK_TIMEOUT)
        if not acquired:
            logger.info("activity_receiver: another drain is already in flight, skipping this ping")
            return ActivityDrainResult(ran=False, error="already running")
        ensure_cursor_row(db, cursor_name=CURSOR_NAME)
        cursor = load_cursor(db, cursor_name=CURSOR_NAME)
        since = cursor.activity_cursor if cursor is not None else None

    result = ActivityDrainResult(ran=True)
    pass_started_at = now
    complete = True
    failure: Optional[BaseException] = None

    # Own budgets, kept separate from the sweep's own running pass for
    # the reasons documented on each constant above/in `sweep_service`.
    order_fetch_budget = [MAX_ACTIVITY_ORDER_FETCHES_PER_PASS]
    shipment_budget = [MAX_WINDOW_FETCHES_PER_PASS]
    cost_budget = [MAX_COST_FETCHES_PER_PASS]
    payment_budget = [MAX_PAYMENT_FETCHES_PER_PASS]

    # `process_batch` folds its counters into whatever `SweepResult` it is
    # given; this drain does not report those counters itself (the ping
    # endpoint reports THIS module's own event/order counters), but
    # `process_batch` requires one to accumulate into across every chunk
    # of this pass.
    batch_result = SweepResult(ran=True)
    seen_this_pass: Dict[int, bool] = {}

    try:
        while True:
            if _pass_deadline_reached(pass_started_at):
                logger.warning("activity_receiver: pass deadline reached before the next page fetch; stopping")
                complete = False
                result.budget_exhausted = True
                break

            page = resolve_maybe_async(ml_webhook_client.get_activity(since=since))
            if page is None:
                # Retryable (timeout/network/5xx) -- NOT a persistent
                # error like an invalid cursor. Stop this pass without
                # advancing; the same `since` is retried next run.
                logger.warning("activity_receiver: get_activity returned no page (retryable); stopping this pass")
                complete = False
                break

            events = page.get("events") or []
            has_more = bool(page.get("has_more"))
            next_cursor = page.get("next_cursor")

            result.pages_walked += 1
            result.events_seen += len(events)

            new_order_ids, without_order_id = _collect_new_order_ids(events, seen_this_pass)
            result.events_without_order_id += without_order_id

            resolved_raw_orders: List[Dict[str, Any]] = []
            page_seen: Dict[int, bool] = {}
            page_not_attempted = 0
            for order_id in new_order_ids:
                if order_fetch_budget[0] <= 0 or _pass_deadline_reached(pass_started_at):
                    page_not_attempted += 1
                    continue
                order_fetch_budget[0] -= 1
                try:
                    raw_order = resolve_maybe_async(ml_webhook_client.get_order(order_id))
                except Exception:
                    logger.warning(
                        "activity_receiver: order_id=%s fetch raised unexpectedly; treated as unresolved",
                        order_id,
                        exc_info=True,
                    )
                    raw_order = None

                if isinstance(raw_order, dict):
                    seen_this_pass[order_id] = True
                    page_seen[order_id] = True
                    resolved_raw_orders.append(raw_order)
                    result.orders_resolved += 1
                else:
                    seen_this_pass[order_id] = False
                    page_seen[order_id] = False
                    result.orders_unresolved += 1

            if page_not_attempted:
                result.orders_not_attempted += page_not_attempted

            # The debt of this page's misses is persisted BEFORE the
            # cursor can move past them, and the debt of orders that
            # resolved this time is cleared in the same session.
            page_resolved_ids = [oid for oid, ok in page_seen.items() if ok]
            page_unresolved_ids = [oid for oid, ok in page_seen.items() if not ok]
            if page_resolved_ids or page_unresolved_ids:
                with get_background_db() as db:
                    _clear_unresolved_orders(db, page_resolved_ids)
                    for order_id in page_unresolved_ids:
                        _record_unresolved_order(db, order_id)

            # HTTP-before-write: every `get_order` call for this page is
            # already done above. `process_batch` itself does its own
            # HTTP (shipment/payment fetch) before ITS write session
            # opens -- unchanged, reused as-is.
            for start in range(0, len(resolved_raw_orders), BATCH_SIZE):
                chunk = resolved_raw_orders[start : start + BATCH_SIZE]
                process_batch(
                    chunk,
                    window_from_floor,
                    batch_result,
                    shipment_budget,
                    cost_budget,
                    pass_started_at,
                    payment_budget,
                )

            # Fold `process_batch`'s own accounting into ours. Without
            # this the drain reports "resolved" and stops there, which is
            # only the HTTP half of the story -- an order can be resolved
            # and then dropped on the floor for a mapping error, and a
            # result that cannot say so is a result that lies.
            result.orders_upserted = batch_result.orders_upserted
            result.orders_skipped_stale = batch_result.orders_skipped_stale
            result.orders_mapping_error = batch_result.orders_mapping_error
            result.orders_out_of_window = batch_result.orders_out_of_window

            if page_not_attempted:
                # The budget (or the deadline) was spent before every new
                # order id on THIS page got a fetch -- this page is not
                # fully handled. Do NOT advance past it: `since` stays
                # put, so the identical page (same events, same
                # still-owed order ids) is re-asked next run instead of
                # silently skipping whatever this pass could not reach.
                complete = False
                result.budget_exhausted = True
                break

            if not isinstance(next_cursor, str) or not next_cursor:
                # The bridge did not hand back a usable cursor. Writing
                # this into `activity_cursor` would persist NULL -- the
                # exact "silent reset back to never-drained" the module
                # docstring promises is impossible, and the next run
                # would re-drain the whole feed from zero. With
                # `has_more` still true it is also an infinite loop:
                # `since` returns to the start, `seen_this_pass`
                # suppresses every `get_order`, and the walk spins
                # against the bridge until the pass deadline. Treat it
                # like an unusable page: keep `since` intact, do not
                # stamp the pass complete, and stop.
                logger.error(
                    "activity_receiver: bridge returned no usable next_cursor (%r) with has_more=%r; "
                    "keeping activity_cursor=%r and stopping this pass",
                    next_cursor,
                    has_more,
                    since,
                )
                complete = False
                result.error = "bridge returned no usable next_cursor"
                break

            # Every order id this page introduced is resolved (or
            # genuinely answered "no" by ML) and its batch(es) committed
            # above -- ONLY NOW is it safe to move the cursor past it.
            with get_background_db() as db:
                # `ensure_cursor_row` already guaranteed this row exists
                # before the loop started.
                write_cursor = load_cursor(db, cursor_name=CURSOR_NAME)
                write_cursor.activity_cursor = next_cursor
            since = next_cursor

            if not has_more:
                break
    except ActivityCursorRejected as e:
        # Deliberately NOT caught earlier: the bridge rejected the
        # cursor outright, which must be visible and operator-
        # actionable, never silently reset to zero (module docstring).
        logger.error("activity_receiver: bridge rejected activity_cursor=%r: %s", since, e)
        failure = e
        result.error = str(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("activity_receiver: drain failed unexpectedly, releasing the run lock")
        failure = e
        result.error = f"{type(e).__name__}: {e}"
    finally:
        if failure is not None:
            release_lock_as_error(failure, cursor_name=CURSOR_NAME)
        else:
            release_lock_as_idle(now, complete=complete, cursor_name=CURSOR_NAME)

    if result.budget_exhausted:
        logger.warning(
            "activity_receiver: pass stopped early (order fetch budget %d or deadline); next run resumes "
            "from the same cursor",
            MAX_ACTIVITY_ORDER_FETCHES_PER_PASS,
        )

    return result
