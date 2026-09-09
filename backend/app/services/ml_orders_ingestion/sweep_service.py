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
  order in a leaf sub-window (proxy down/5xx/timeout), NOTHING is written
  for that leaf and the cursor is NOT advanced past it, so the same leaf
  is retried on the next run.
- An order ML reports as updated whose own `date_created` falls outside
  the configured rolling window is a HARD EXCLUSION -- never ingested --
  but IS counted, via `ml_ops_divergence.kind='out_of_window_update'`
  (obs #1824 deferred-decision instrumentation, obs #1828 cross-slice
  schema contract).

Memory and checkpointing (post-review fix, GGA pre-push round 1): a cold
start with no cursor spans the FULL rolling window (90-180 days). Orders
are never accumulated into one in-memory list for the whole window -- they
are processed incrementally, leaf sub-window by leaf sub-window, in
BATCH_SIZE-bounded chunks, and the cursor's `window_to` is advanced after
EACH leaf sub-window completes (not only once at the very end). This makes
a cold start durable: if the process dies or a LATER leaf fails, every
EARLIER leaf's writes and cursor progress survive, and a retry resumes
from there instead of redoing the whole window. The fail-closed guarantee
still holds: a failed leaf's own writes/checkpoint never happen, so the
cursor never jumps past a leaf that failed.

Unenumerable windows (post-review fix): a leaf that still reports more
rows than the offset cap even at the minimum bisectable span cannot be
enumerated at all. Previously this raised and wedged the sweep on that
exact leaf forever (retried identically every run, no operational way out
short of editing the database). It is now recorded --
`ml_ops_divergence.kind='window_not_enumerable'` -- and the sweep moves
past it, exactly like an out-of-window order: hard exclusion +
instrumentation instead of a silent permanent stall.

Concurrency (post-review fix): `ml_ops_sync_cursor.state` is 'running' for
the ENTIRE duration of a pass (not just at checkpoint time), so an
overlapping cron invocation (a cold start can easily exceed the 10-minute
cadence, see above) skips instead of racing the same cursor. A 'running'
lock left behind by a process that died is reclaimed after
STALE_LOCK_TIMEOUT rather than wedging the sweep permanently -- the same
class of bug as the unenumerable-window stall, given the same treatment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_orders_ops import (
    UNENUMERABLE_KIND,
    MlOpsDivergence,
    MlOpsSyncCursor,
    MlOrdersOps,
    MlShipmentOps,
)
from app.services.ml_orders_ingestion.ingestion_service import UpsertOutcome, upsert_order, upsert_shipment
from app.services.ml_orders_ingestion.mapper import MappingError, map_order
from app.services.ml_payments_ingestion.ingestion_service import upsert_payment
from app.services.ml_payments_ingestion.mapper import MappingError as PaymentMappingError
from app.services.ml_payments_ingestion.mapper import map_payment
from app.services.ml_webhook_client import ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

# ML's `/orders/search` offset cap is ~1000; stay comfortably under it so a
# window whose true total sits right at the boundary still bisects instead
# of risking a partial page.
SEARCH_PAGE_SIZE_CAP = 950

# Bounded batch per `get_background_db()` session (design D8): a batch is
# flushed either when it reaches this size or when a leaf sub-window
# finishes, whichever comes first -- memory is bounded to O(BATCH_SIZE),
# never O(window size).
BATCH_SIZE = 200

# Absorbs ML's own update-visibility lag between sweep passes. Free because
# the upsert is idempotent (design D5) -- re-processing the overlap is a
# structural no-op for anything already stored.
CURSOR_OVERLAP = timedelta(minutes=15)

# Below this window width, further bisection is pointless (and would loop
# forever against a window that genuinely never drops below the cap). A
# leaf this narrow that still overflows is recorded as unenumerable
# instead (see module docstring).
MIN_BISECT_SPAN = timedelta(minutes=1)

# Bisection is recursive, so an inflated or bogus `paging.total` would
# recurse to the 1-minute floor: 180 days is 259,200 leaves, each one an
# HTTP call to the ML proxy. A pass spends at most this many fetches and
# then stops; the cursor keeps whatever leaves it did complete, so the
# next pass resumes instead of starting over.
MAX_WINDOW_FETCHES_PER_PASS = 2000

# ml-ventas-desglose-costos corte 4: separate allowance for
# `get_shipment_costs`. Kept apart from `MAX_WINDOW_FETCHES_PER_PASS`
# (search pages + `get_shipment`) on purpose -- a first pass after this
# cut can find thousands of already-ingested shipments with
# `costs_synced_at IS NULL`, and letting cost sync compete with page
# walking for the same shared budget would starve order ingestion itself
# on that first pass. Each unsynced shipment is one extra HTTP call
# (`get_shipment_costs`), so this caps that pass's added HTTP cost while
# still guaranteeing forward progress every 10-minute run: at 500/pass a
# backlog of a few thousand terminal shipments drains within a handful of
# passes, not one.
MAX_COST_FETCHES_PER_PASS = 500

# ml-ventas-desglose-costos corte 5: separate allowance for `get_payment`.
# Kept apart from the other two budgets for the same reason as
# `MAX_COST_FETCHES_PER_PASS`: a backlog on one HTTP-bound step must
# never starve another step's own budget on the same pass. No live rate
# limit was found on this endpoint (514 payments fetched back-to-back,
# zero 429s) -- this cap exists for pass-shape symmetry with the other
# two, not because ML throttles it.
MAX_PAYMENT_FETCHES_PER_PASS = 500

# A 'running' lock older than this is assumed to belong to a dead process
# and is reclaimed rather than blocking the sweep forever. Well above the
# 10-minute cron cadence so a legitimately slow (e.g. cold-start) pass is
# never mistaken for a stale one.
STALE_LOCK_TIMEOUT = timedelta(minutes=30)

# A WALL-CLOCK ceiling for the whole pass, above any call budget.
#
# `run_sweep`'s comment used to say there was ONE budget because "two
# separate budgets would each stay under their own limit while the pass as a
# whole ran far past the stale-lock timeout". Corte 4 added exactly that
# second budget -- for a good reason, starving the order walk -- and so
# reopened the other side: 2000 + 500 sequential calls against a lock
# reclaimed after 30 minutes, and two sweeps on one cursor.
#
# Counting calls cannot close that; every new budget reopens it. The limit
# belongs where the risk is, which is the clock. Checked in EVERY fetch loop
# -- the page walk, the shipment lookups and the cost sync -- because a slow
# proxy blows the deadline on the page walk alone, long before the cost
# section is ever reached.
PASS_DEADLINE_MARGIN = timedelta(minutes=5)
PASS_TIME_BUDGET = STALE_LOCK_TIMEOUT - PASS_DEADLINE_MARGIN


def _pass_deadline_reached(started_at: Optional[datetime]) -> bool:
    """True once the pass has spent its time. `None` disables the cutoff,
    for tests that do not exercise it."""
    if started_at is None:
        return False
    return datetime.now(timezone.utc) - started_at >= PASS_TIME_BUDGET


CURSOR_NAME = "sweep"
OUT_OF_WINDOW_KIND = "out_of_window_update"
# UNENUMERABLE_KIND now lives on the model (app/models/ml_orders_ops.py) --
# it describes a value of that table's `kind` column, and the divergence
# detector/dashboard router need it too. Imported above, not redefined.


class WindowFetchError(Exception):
    """A leaf sub-window's orders could not be fully enumerated. Fail-
    closed at the leaf level: the caller must NOT write anything further
    for this leaf and must NOT advance the cursor past it."""


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
    windows_unenumerable: int = 0
    # Without this there is no way to see from outside whether the cost
    # backlog is draining or spending its budget every pass without moving.
    shipment_costs_synced: int = 0
    payments_synced: int = 0
    budget_exhausted: bool = False
    error: Optional[str] = None


# ── Streaming window walk ──────────────────────────────────────────────
#
# `iter_window_events` recursively bisects [date_from, date_to) and
# yields events AS SOON AS each one is known, so the caller never has to
# hold more than one page (bounded by BATCH_SIZE) in memory:
#   ("page", [raw_order, ...])       -- one fetched page, chronological
#   ("unenumerable", leaf_from, leaf_to)  -- a leaf that could not be
#                                            bisected further and still
#                                            overflows the offset cap
#   ("checkpoint", leaf_to)          -- a leaf sub-window is FULLY
#                                        accounted for (every page fetched,
#                                        or recorded unenumerable); safe to
#                                        advance the cursor's window_to to
#                                        leaf_to
# Raises WindowFetchError for a leaf whose HTTP fetch fails outright
# (proxy down/5xx/timeout/unparseable paging) -- NOT for an unbisectable
# overflow, which is recorded and swept past instead (see module
# docstring).


def iter_window_events(
    seller_id: int,
    date_from: datetime,
    date_to: datetime,
    budget: Optional[List[int]] = None,
    started_at: Optional[datetime] = None,
) -> Iterator[Tuple[str, Any]]:
    if budget is None:
        budget = [MAX_WINDOW_FETCHES_PER_PASS]
    # The clock counts here too, not only in the cost sync. A slow proxy
    # blows the deadline on the page walk alone -- 2000 pages at 1.2s is 40
    # minutes against a lock reclaimed at 30 -- long before the cost
    # section is ever reached. Same signal as an exhausted budget, so the
    # cursor does not advance past what was actually read.
    if budget[0] <= 0 or _pass_deadline_reached(started_at):
        yield ("budget_exhausted", date_from, date_to)
        return
    budget[0] -= 1
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
            # Escape hatch (finding 3): cannot bisect further but still
            # over cap -- record it and move on instead of raising, which
            # would retry this EXACT leaf forever with no way out.
            yield ("unenumerable", date_from, date_to)
            yield ("checkpoint", date_to)
            return
        midpoint = date_from + span / 2
        yield from iter_window_events(seller_id, date_from, midpoint, budget, started_at)
        yield from iter_window_events(seller_id, midpoint, date_to, budget, started_at)
        return

    # Leaf window within cap -- page through it, yielding each page as
    # soon as it is fetched.
    page_results: List[Dict[str, Any]] = list(response.get("results") or [])
    yield ("page", page_results)
    offset = len(page_results)
    while offset < total:
        # Pages are charged too. Spending the budget only at offset=0 let a
        # single leaf issue ~19 requests for one unit, which made the
        # documented ceiling wrong by more than an order of magnitude.
        if budget[0] <= 0:
            yield ("budget_exhausted", date_from, date_to)
            return
        budget[0] -= 1
        page = resolve_maybe_async(ml_webhook_client.search_orders(seller_id, date_from, date_to, offset=offset))
        if page is None:
            raise WindowFetchError(
                f"search_orders failed at offset={offset} for window [{date_from.isoformat()}, {date_to.isoformat()})"
            )
        page_results = list(page.get("results") or [])
        if not page_results:
            break
        yield ("page", page_results)
        offset += len(page_results)

    yield ("checkpoint", date_to)


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
            MlOpsDivergence.kind == OUT_OF_WINDOW_KIND,
            MlOpsDivergence.field.is_(None),
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.detected_at = now
    else:
        db.add(MlOpsDivergence(order_id=order_id, kind=OUT_OF_WINDOW_KIND, detected_at=now))


def _unenumerable_field_key(date_from: datetime, date_to: datetime) -> str:
    """Dedup key for an unenumerable leaf, as epoch seconds. ISO bounds
    would be 51 characters against a `String(40)` column -- which SQLite
    ignores and Postgres rejects, inside the one code path whose purpose
    is to keep the sweep running."""
    return f"{int(date_from.timestamp())}|{int(date_to.timestamp())}"


def record_unenumerable_window(db, date_from: datetime, date_to: datetime) -> None:
    """Escape hatch for a leaf window that cannot be enumerated at all
    (finding 3): recorded, never ingested, never silently dropped. There
    is no single order to key this on -- `order_id=0` is a sentinel (the
    column is NOT NULL) and the leaf's own bounds are the dedup key via
    `field`, so a repeat detection of the SAME leaf updates `detected_at`
    instead of duplicating (unique `(order_id, kind, field)`).

    UNBOUNDED GROWTH, on purpose, for now: a dense region bisected to the
    one-minute floor yields one row per minute, and since the checkpoint
    advances, later passes produce fresh bounds rather than matching these.
    Nothing collapses or expires them. That is acceptable while this is the
    only signal that a window could not be read at all, but the slice that
    builds the divergence dashboard MUST (a) filter or label the
    `order_id=0` sentinel so it is not rendered as an order, and (b) decide
    a retention or collapse policy for these rows."""
    field_key = _unenumerable_field_key(date_from, date_to)
    existing = (
        db.query(MlOpsDivergence)
        .filter(
            MlOpsDivergence.order_id == 0,
            MlOpsDivergence.kind == UNENUMERABLE_KIND,
            MlOpsDivergence.field == field_key,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.detected_at = now
    else:
        db.add(
            MlOpsDivergence(
                order_id=0,
                kind=UNENUMERABLE_KIND,
                field=field_key,
                ml_value=date_from.isoformat(),
                gbp_value=date_to.isoformat(),
                detected_at=now,
            )
        )


def _fetch_shipments(
    raw_orders: List[Dict[str, Any]],
    budget: Optional[List[int]] = None,
    started_at: Optional[datetime] = None,
) -> Dict[int, Dict[str, Any]]:
    """Fetches the shipment payload for every order that carries a
    `shipping.id`, entirely BEFORE any DB session opens (same HTTP-before-
    write discipline as the order/page fetch above -- design D8).

    Best-effort per shipment: a failed fetch is logged and skipped rather
    than raised, so one flaky shipment lookup never turns into a
    `WindowFetchError` that discards an otherwise-good page of orders.

    Shares the pass's `budget` with the page fetches. A cold start would
    otherwise issue one lookup per order, sequentially, for as many orders
    as the window holds -- long past the stale-lock timeout, so a second
    pass would start on top of the first. A caller that passes none gets a
    fresh per-batch allowance rather than no limit at all.
    """
    if budget is None:
        budget = [MAX_WINDOW_FETCHES_PER_PASS]
    shipments: Dict[int, Dict[str, Any]] = {}
    for raw_order in raw_orders:
        shipping = raw_order.get("shipping")
        if not isinstance(shipping, dict):
            continue
        raw_shipping_id = shipping.get("id")
        if raw_shipping_id is None:
            continue
        try:
            shipping_id = int(raw_shipping_id)
        except (TypeError, ValueError):
            continue
        if shipping_id in shipments:
            continue
        if _pass_deadline_reached(started_at):
            logger.warning("sweep: pass ran out of time before every shipment was read; the next one resumes")
            break
        if budget[0] <= 0:
            logger.warning("sweep: fetch budget spent before every shipment was read; the next pass resumes")
            break
        budget[0] -= 1
        try:
            payload = resolve_maybe_async(ml_webhook_client.get_shipment(shipping_id))
        except Exception:
            logger.warning("sweep: shipment fetch failed for shipping_id=%s", shipping_id, exc_info=True)
            continue
        if isinstance(payload, dict):
            shipments[shipping_id] = payload
    return shipments


def _extract_payment_ids(raw_order: Dict[str, Any]) -> List[int]:
    """`order.payments[].id`, order-preserving dedup, coerced to `int` --
    the search page already carries this array, so no extra HTTP call is
    needed to discover which payments to fetch."""
    raw_payments = raw_order.get("payments")
    if not isinstance(raw_payments, list):
        return []
    seen: set = set()
    ids: List[int] = []
    for entry in raw_payments:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        if raw_id is None:
            continue
        try:
            payment_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if payment_id not in seen:
            seen.add(payment_id)
            ids.append(payment_id)
    return ids


def _fetch_payments(
    raw_orders: List[Dict[str, Any]],
    budget: Optional[List[int]] = None,
    started_at: Optional[datetime] = None,
) -> Dict[int, Dict[str, Any]]:
    """Fetches every `order.payments[].id` on `raw_orders`, entirely
    BEFORE any DB session opens (same HTTP-before-write discipline as
    `_fetch_shipments` -- design D8).

    Fail-open per payment, same discipline as `_fetch_shipments` and
    `_sync_shipment_costs`: one failed fetch is logged and skipped, never
    raised, so a single flaky payment lookup never turns into a
    `WindowFetchError` that discards an otherwise-good batch.
    """
    if budget is None:
        budget = [MAX_PAYMENT_FETCHES_PER_PASS]
    payments: Dict[int, Dict[str, Any]] = {}
    for raw_order in raw_orders:
        for payment_id in _extract_payment_ids(raw_order):
            if payment_id in payments:
                continue
            if _pass_deadline_reached(started_at):
                logger.warning("sweep: pass ran out of time before every payment was read; the next one resumes")
                return payments
            if budget[0] <= 0:
                logger.warning("sweep: payment-fetch budget spent before every payment was read; the next pass resumes")
                return payments
            budget[0] -= 1
            try:
                payload = resolve_maybe_async(ml_webhook_client.get_payment(payment_id))
            except Exception:
                logger.warning("sweep: payment fetch failed for payment_id=%s", payment_id, exc_info=True)
                continue
            if isinstance(payload, dict):
                payments[payment_id] = payload
    return payments


PAYMENTS_KEY_MISSING_FIELD = "payments_key_missing"


def _record_payments_key_missing(db, order_id: int) -> None:
    """ML's own order payload omitted `payments[]` entirely -- not the
    same fact as `payments: []` (see `sync_payments_for_order`'s
    docstring). This only ever runs for a raw order FRESH off
    `search_orders`/`get_order`, so the omission IS ML's own answer and
    it is safe to treat as "no payments" -- but that must stay VISIBLE
    instead of silently vanishing into a seal, exactly like
    `record_unenumerable_window`'s escape hatch for a leaf that cannot be
    enumerated. Reuses the generic `kind='unknown'` bucket: the CHECK
    constraint on `ml_ops_divergence.kind` has no dedicated value for
    this and a migration is out of scope for this fix. Re-detection
    updates `detected_at`, deduped by the `(order_id, kind, field)`
    unique constraint."""
    existing = (
        db.query(MlOpsDivergence)
        .filter(
            MlOpsDivergence.order_id == order_id,
            MlOpsDivergence.kind == "unknown",
            MlOpsDivergence.field == PAYMENTS_KEY_MISSING_FIELD,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.detected_at = now
    else:
        db.add(MlOpsDivergence(order_id=order_id, kind="unknown", field=PAYMENTS_KEY_MISSING_FIELD, detected_at=now))


def sync_payments_for_order(
    db,
    order_id: int,
    raw_order: Dict[str, Any],
    payments_payload: Dict[int, Dict[str, Any]],
    missing_key_is_empty: bool = False,
) -> Tuple[int, bool]:
    """Maps and persists every `raw_order['payments'][].id` present in
    `payments_payload`, then seals `MlOrdersOps.payments_synced_at` ONLY
    if every one of this order's payment ids resolved. A partial result
    (a missing id, a fetch failure already excluded from
    `payments_payload`, or a mapping error) leaves it NULL so the retry
    gate (`payments_synced_at IS NULL`) picks it up again next pass.

    Extracted (post-review fix, ml-backfill-pagos-y-costos) so the sweep's
    own `process_batch` and the historical backfill
    (`app/scripts/backfill_ml_payments_costs.py`) share this EXACT
    sealing rule instead of drifting into two implementations of the same
    money-path logic. Returns `(payments_synced, sealed)`.

    The `payments`
    key ABSENT is not the same fact as `payments` present and EMPTY.
    ML's own order schema guarantees the key on every live order, so
    `payments: []` means "ML says this order genuinely has none" -- fine
    to seal. The key being absent means the SOURCE never told us either
    way -- UNLESS the caller can vouch that `raw_order` is genuinely
    fresh off ML (`missing_key_is_empty=True`), in which case the
    omission itself IS ML's answer and sealing is correct (the sweep's
    `process_batch` also records `_record_payments_key_missing` first, so
    this stays visible rather than silently vanishing).

    The default (`missing_key_is_empty=False`) is for a `raw_order` NOT
    guaranteed fresh -- e.g. the backfill's first read of
    `MlOrdersOps.raw_order`, written by whatever ingestion version was
    running at the time, which may have truncated, half-written, or
    otherwise never persisted this field. Sealing on an ABSENT key there
    converts an unknown into "zero payments, done" -- and since
    `payments_synced_at IS NULL` is the ONLY retry gate, that order could
    never become a candidate again. The backfill
    itself now refetches such an order fresh from ML BEFORE ever calling
    this function with `missing_key_is_empty=True`, instead of leaving it
    permanently unresolved -- see `backfill_payments_costs_service.py`."""
    if raw_order.get("payments") is None and not missing_key_is_empty:
        return 0, False
    payment_ids = _extract_payment_ids(raw_order)
    synced = 0
    all_synced = True
    for payment_id in payment_ids:
        payment_payload = payments_payload.get(payment_id)
        if payment_payload is None:
            all_synced = False
            continue
        mapped_payment = map_payment(payment_payload)
        if isinstance(mapped_payment, PaymentMappingError):
            logger.warning(
                "sync_payments_for_order: payment mapping error for payment_id=%s (order_id=%s): %s",
                payment_id,
                order_id,
                mapped_payment.reason,
            )
            all_synced = False
            continue
        upsert_payment(db, mapped_payment)
        synced += 1
    if all_synced:
        db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).update(
            {"payments_synced_at": datetime.now(timezone.utc)}
        )
    return synced, all_synced


def tz_aware(value: Optional[datetime]) -> Optional[datetime]:
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


# A shipment in one of these has finished moving: the goods reached the
# buyer, or came back. Anything else is still in flight and can change
# without the order changing with it.
TERMINAL_SHIPMENT_STATUSES = frozenset({"delivered", "not_delivered", "cancelled"})


def _stored_ml_last_updated(order_ids: List[int]) -> Dict[int, Optional[datetime]]:
    """The `ml_last_updated` already stored for these orders, in one query.
    Missing keys mean the order is new. Read-only and short-lived."""
    if not order_ids:
        return {}
    with get_background_db() as db:
        rows = (
            db.query(MlOrdersOps.order_id, MlOrdersOps.ml_last_updated)
            .filter(MlOrdersOps.order_id.in_(order_ids))
            .all()
        )
    return {order_id: tz_aware(stored) for order_id, stored in rows}


def _orders_with_payments_synced(order_ids: List[int]) -> set:
    """Orders whose `payments_synced_at` is already set, in one query --
    the ONLY retry gate for `order.payments[]` ingestion (post-review
    fix), mirroring `_shipments_needing_cost_sync`'s `costs_synced_at IS
    NULL` gate: independent of the order's own staleness, so a payment
    fetch that failed on a PRIOR pass (timeout, spent budget) is retried
    on every later pass until it actually succeeds -- never silently
    abandoned just because the order itself stopped being stale."""
    if not order_ids:
        return set()
    with get_background_db() as db:
        rows = (
            db.query(MlOrdersOps.order_id)
            .filter(MlOrdersOps.order_id.in_(order_ids), MlOrdersOps.payments_synced_at.isnot(None))
            .all()
        )
    return {order_id for (order_id,) in rows}


def _orders_with_a_settled_shipment(order_ids: List[int]) -> set:
    """Orders whose stored shipment has finished moving, in one query.

    Skipping an unchanged order's shipment assumes Mercado Libre bumps the
    ORDER's `date_last_updated` whenever the SHIPMENT moves. That is not
    verified, and if it does not hold in some case, the shipment freezes
    and the listing's goods column lies about where the product is. A
    shipment that already reached a terminal status cannot move again, so
    it is the only one safe to skip on that assumption."""
    if not order_ids:
        return set()
    with get_background_db() as db:
        rows = (
            db.query(MlShipmentOps.order_id)
            .filter(
                MlShipmentOps.order_id.in_(order_ids),
                MlShipmentOps.status.in_(tuple(TERMINAL_SHIPMENT_STATUSES)),
            )
            .all()
        )
    return {order_id for (order_id,) in rows}


def _extract_sender_cost(payload: Dict[str, Any]) -> Optional[Decimal]:
    """The seller's real charge is `senders[0].cost`, taken AS-IS from ML --
    NEVER derived from `base_cost/2` or any other calculation: `base_cost`
    can be the PRE-discount figure and the discount (`senders[0].discounts[]`)
    is itself mutable (investigation §1)."""
    senders = payload.get("senders")
    if not isinstance(senders, list) or not senders:
        return None
    first = senders[0]
    if not isinstance(first, dict):
        return None
    cost = first.get("cost")
    if cost is None:
        return None
    try:
        return Decimal(str(cost))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _extract_receiver_cost(payload: Dict[str, Any]) -> Optional[Decimal]:
    """Persisted alongside `sender_cost` -- corte 5 (tax breakdown) needs it
    as the base for the buyer-side tax calculation."""
    receiver = payload.get("receiver")
    if not isinstance(receiver, dict):
        return None
    cost = receiver.get("cost")
    if cost is None:
        return None
    try:
        return Decimal(str(cost))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _shipments_needing_cost_sync(shipment_ids: List[int]) -> List[int]:
    """Shipments already stored (order/webhook ingestion writes the row
    first) that have never had their costs synced. `costs_synced_at IS
    NULL` is the ONLY gate -- independent of shipment status: a terminal
    shipment without synced costs must still be synced exactly once."""
    if not shipment_ids:
        return []
    with get_background_db() as db:
        rows = (
            db.query(MlShipmentOps.shipment_id)
            .filter(
                MlShipmentOps.shipment_id.in_(shipment_ids),
                MlShipmentOps.costs_synced_at.is_(None),
            )
            .all()
        )
    return [shipment_id for (shipment_id,) in rows]


def _sync_shipment_costs(
    shipment_ids: List[int],
    budget: Optional[List[int]] = None,
    started_at: Optional[datetime] = None,
    attempted_out: Optional[Set[int]] = None,
) -> int:
    """Fetches and persists `sender_cost`/`receiver_cost` for every shipment
    in `shipment_ids` whose `costs_synced_at` is still NULL.

    Fail-open per shipment (same discipline as `_fetch_shipments`): one
    shipment whose cost fetch fails (network error, the SSRF guard raising
    for a non-coercible id, a malformed payload) is logged and skipped --
    it never blocks the rest of the batch or turns into a `WindowFetchError`
    that would discard the pass. `costs_synced_at` stays NULL for that
    shipment, so the next pass retries it.

    HTTP happens entirely before any DB session opens for the write, same
    HTTP-before-write discipline as `_fetch_shipments` (design D8).

    `attempted_out`, when given, collects the ids this call actually
    spent an HTTP fetch on. A shipment skipped because the budget or the
    pass deadline ran out never reaches ML, so a caller that counts
    give-up attempts must not charge it one -- see the backfill's
    `_record_cost_sync_attempt` call site.
    """
    to_sync = _shipments_needing_cost_sync(shipment_ids)
    if not to_sync:
        return 0
    if budget is None:
        budget = [MAX_COST_FETCHES_PER_PASS]

    fetched: Dict[int, Dict[str, Any]] = {}
    for shipment_id in to_sync:
        if _pass_deadline_reached(started_at):
            logger.warning("sweep: pass ran out of time during cost sync; the next one resumes")
            break
        if budget[0] <= 0:
            logger.warning(
                "sweep: cost-fetch budget spent before every unsynced shipment was read; the next pass resumes"
            )
            break
        budget[0] -= 1
        if attempted_out is not None:
            attempted_out.add(shipment_id)
        try:
            payload = resolve_maybe_async(ml_webhook_client.get_shipment_costs(shipment_id))
        except Exception:
            logger.warning("sweep: shipment cost fetch failed for shipment_id=%s", shipment_id, exc_info=True)
            continue
        if isinstance(payload, dict):
            fetched[shipment_id] = payload

    if not fetched:
        return 0

    now = datetime.now(timezone.utc)
    synced = 0
    with get_background_db() as db:
        rows = db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id.in_(fetched.keys())).all()
        for row in rows:
            payload = fetched.get(row.shipment_id)
            if payload is None:
                continue
            sender = _extract_sender_cost(payload)
            receiver = _extract_receiver_cost(payload)
            # Write only what actually arrived, and seal only when BOTH
            # arrived. `costs_synced_at IS NULL` is the ONLY retry gate, so
            # stamping it here on a partial payload loses the missing cost
            # forever -- on the money path -- and overwrites with NULL
            # whatever a previous pass had already stored. Not
            # hypothetical: this is what ML returns while a shipment's
            # costs are not settled yet, and `receiver_cost` is what corte
            # 5 needs as the tax base.
            if sender is None and receiver is None:
                logger.warning(
                    "sweep: cost payload carried no usable costs for shipment_id=%s; left for the next pass",
                    row.shipment_id,
                )
                continue
            if sender is not None:
                row.sender_cost = sender
            if receiver is not None:
                row.receiver_cost = receiver
            if sender is None or receiver is None:
                logger.warning(
                    "sweep: partial cost payload for shipment_id=%s (sender=%s receiver=%s); not sealed",
                    row.shipment_id,
                    sender is not None,
                    receiver is not None,
                )
                continue
            row.costs_synced_at = now
            synced += 1
    return synced


def process_batch(
    raw_orders: List[Dict[str, Any]],
    window_from_floor: datetime,
    result: SweepResult,
    budget: Optional[List[int]] = None,
    cost_budget: Optional[List[int]] = None,
    pass_started_at: Optional[datetime] = None,
    payment_budget: Optional[List[int]] = None,
) -> None:
    """Upserts one bounded batch in its OWN short-lived session. Every
    shipment payload was already fetched (HTTP-only, see `_fetch_shipments`)
    BEFORE this function is called -- no HTTP call happens inside this
    block, only the order/shipment payloads already in hand.

    Counters accumulate in locals and are folded into `result` only once
    the session exits cleanly. Incrementing `result` row by row inside the
    block would report writes that a rollback had undone -- the same
    "metric that lies by construction" this function already guards
    against in its DISABLED branch."""
    seen = upserted = skipped_stale = mapping_error = out_of_window = 0

    # Map and classify first: both are pure, so they cost nothing, and they
    # decide which orders are actually going to be written. Fetching a
    # shipment for an order the window excludes would spend a slot of the
    # shared budget the page walk needs, for a row that is never ingested.
    classified: List[tuple[Dict[str, Any], Any]] = []
    for raw_order in raw_orders:
        seen += 1
        mapped = map_order(raw_order)
        if isinstance(mapped, MappingError):
            mapping_error += 1
            logger.warning("sweep: mapping error for a search result: %s", mapped.reason)
            continue
        classified.append((raw_order, mapped))

    in_window = [
        (raw_order, mapped)
        for raw_order, mapped in classified
        if not (mapped.date_created is not None and mapped.date_created < window_from_floor)
    ]

    # `CURSOR_OVERLAP` makes every pass reprocess the last stretch of the
    # previous one on purpose, so in steady state most of a batch upserts to
    # SKIPPED_STALE. Fetching those shipments would spend the shared budget
    # on writes that never happen -- the common case, not an edge. One
    # read-only query answers which orders are already at this version;
    # reading is not writing, so the HTTP-before-write discipline holds.
    in_window_ids = [mapped.order_id for _, mapped in in_window]
    stored_versions = _stored_ml_last_updated(in_window_ids)
    settled_shipments = _orders_with_a_settled_shipment(in_window_ids)
    ingestable = [
        (raw_order, mapped)
        for raw_order, mapped in in_window
        if stored_versions.get(mapped.order_id) is None
        or mapped.ml_last_updated > stored_versions[mapped.order_id]
        or mapped.order_id not in settled_shipments
    ]
    shipments = _fetch_shipments([raw for raw, _ in ingestable], budget, started_at=pass_started_at)

    # Payments (corte 5, post-review fix) are gated by the UNION of two
    # triggers:
    #   1. The order itself is new or genuinely re-ingested (its own
    #      `ml_last_updated` moved forward) -- a return moves an order's
    #      `date_last_updated` and can move its payment(s)' own
    #      status/refund amounts with it, so a real update must always
    #      refetch, EVEN IF this order's payments were already sealed by
    #      an earlier pass.
    #   2. `payments_synced_at IS NULL` -- the actual RETRY gate (finding
    #      1's fix). The original trigger was `UpsertOutcome.OK` alone,
    #      which is (1) by itself: a payment fetch that failed (timeout,
    #      spent budget) on the SAME pass the order upserted successfully
    #      was never retried, because the next pass finds the order no
    #      longer stale and never asks for its payments again -- the
    #      order silently ends up ingested with no net forever. (2)
    #      covers both a brand-new order (never synced) and a
    #      previously-failed one (still NULL), independent of
    #      `ml_last_updated`, mirroring the shipment cost gate.
    stale_trigger_ids = {
        mapped.order_id
        for _, mapped in in_window
        if stored_versions.get(mapped.order_id) is None or mapped.ml_last_updated > stored_versions[mapped.order_id]
    }
    payments_already_synced = _orders_with_payments_synced(in_window_ids)
    payment_candidates = [
        (raw_order, mapped)
        for raw_order, mapped in in_window
        if mapped.order_id in stale_trigger_ids or mapped.order_id not in payments_already_synced
    ]
    payments_payload = _fetch_payments(
        [raw for raw, _ in payment_candidates], payment_budget, started_at=pass_started_at
    )
    payment_candidate_ids = {mapped.order_id for _, mapped in payment_candidates}

    payments_synced = 0
    with get_background_db() as db:
        for raw_order, mapped in classified:
            if mapped.date_created is not None and mapped.date_created < window_from_floor:
                _record_out_of_window(db, mapped.order_id)
                out_of_window += 1
                continue

            outcome = upsert_order(db, raw_order, mapped=mapped)
            if outcome == UpsertOutcome.OK:
                upserted += 1
            elif outcome == UpsertOutcome.SKIPPED_STALE:
                skipped_stale += 1
            elif outcome == UpsertOutcome.MAPPING_ERROR:
                mapping_error += 1
            else:
                # UpsertOutcome.DISABLED: unreachable in practice (run_sweep
                # already checked the flag before starting), but a metric
                # must never lie by construction -- this is NOT a mapping
                # error, so it must not be counted as one.
                logger.error("sweep: upsert_order returned DISABLED mid-window -- flag toggled during a run?")
                continue

            # Payments are synced for BOTH `OK` and `SKIPPED_STALE` --
            # the order row exists either way, and this is the retry gate
            # for a payment fetch that failed on an earlier pass while the
            # order itself was (or has since become) unchanged. Sealed
            # (`payments_synced_at`) ONLY once every one of this order's
            # payment ids resolved to a successfully mapped+persisted
            # payment; a partial failure leaves it NULL so the next pass
            # retries exactly the missing ones (`payments_payload` is
            # re-fetched fresh every pass for any still-NULL order).
            if mapped.order_id in payment_candidate_ids:
                # `raw_order` here is fresh off THIS pass's `search_orders`
                # call (design D5's single source of truth), so an absent
                # `payments` key is ML's own answer, not an unknown --
                # `missing_key_is_empty=True` -- but it is recorded first
                # so it stays visible instead of silently vanishing into a
                # seal (post-review fix #1/#2).
                if raw_order.get("payments") is None:
                    _record_payments_key_missing(db, mapped.order_id)
                order_synced, _sealed = sync_payments_for_order(
                    db, mapped.order_id, raw_order, payments_payload, missing_key_is_empty=True
                )
                payments_synced += order_synced

            # Shipment upsert failures are NOT folded into the order
            # counters above -- a shipment mapping error/staleness says
            # nothing about whether the order itself was written, and
            # conflating the two would make `orders_upserted` lie about
            # what actually happened to the order row.
            if mapped.shipping_id is not None:
                shipment_payload = shipments.get(mapped.shipping_id)
                if shipment_payload is not None:
                    shipment_outcome = upsert_shipment(db, shipment_payload)
                    if shipment_outcome == UpsertOutcome.MAPPING_ERROR:
                        logger.warning(
                            "sweep: shipment mapping error for shipping_id=%s (order_id=%s)",
                            mapped.shipping_id,
                            mapped.order_id,
                        )

    result.orders_seen += seen
    result.orders_upserted += upserted
    result.orders_skipped_stale += skipped_stale
    result.orders_mapping_error += mapping_error
    result.orders_out_of_window += out_of_window
    result.payments_synced += payments_synced

    # Cost sync runs for every shipping_id this batch touched (not just
    # `ingestable`'s subset that got a fresh `get_shipment` fetch): a
    # settled/terminal shipment is deliberately excluded from
    # `_fetch_shipments` above once its own status is stored, but it must
    # still get its costs synced exactly once (`costs_synced_at IS NULL`
    # is the only gate, independent of shipment status).
    shipping_ids_this_batch = sorted({mapped.shipping_id for _, mapped in classified if mapped.shipping_id is not None})
    if shipping_ids_this_batch:
        result.shipment_costs_synced += _sync_shipment_costs(
            shipping_ids_this_batch, cost_budget, started_at=pass_started_at
        )


def load_cursor(db, for_update: bool = False, cursor_name: str = CURSOR_NAME) -> Optional[MlOpsSyncCursor]:
    """`for_update` locks the row for the read-modify-write that claims the
    run lock. Without it two runs both read 'idle' and both proceed, which
    is the exact race the lock exists to prevent. SQLite ignores the hint.

    `cursor_name` is parameterised (default `'sweep'`) so the backfill job
    (slice 5) reuses this exact function under `name='backfill'` instead of
    a second, drifting copy -- see obs #1852 lesson 3."""
    query = db.query(MlOpsSyncCursor).filter_by(name=cursor_name)
    if for_update:
        query = query.with_for_update()
    return query.first()


def ensure_cursor_row(db, cursor_name: str = CURSOR_NAME) -> None:
    """Creates the cursor row if it does not exist, tolerating a concurrent
    creator. Dialect-agnostic: the insert is attempted in a SAVEPOINT so a
    losing racer rolls back only that statement."""
    if db.query(MlOpsSyncCursor).filter_by(name=cursor_name).first() is not None:
        return
    try:
        with db.begin_nested():
            db.add(MlOpsSyncCursor(name=cursor_name, state="idle"))
            db.flush()
    except IntegrityError:
        # Someone else created it between our SELECT and our INSERT, which
        # is exactly the race this exists to survive.
        pass


def release_lock_as_idle(now: datetime, complete: bool = True, cursor_name: str = CURSOR_NAME) -> None:
    """Clears the run lock after a pass that did not raise. `complete` is
    False when the pass stopped early on its fetch budget: it covered only
    part of the window, so stamping `last_success_at` would record partial
    work as a finished sweep. Swallows its own failures for the same
    reason as `release_lock_as_error`."""
    try:
        with get_background_db() as db:
            cursor = load_cursor(db, cursor_name=cursor_name)
            if cursor is None:
                cursor = MlOpsSyncCursor(name=cursor_name)
                db.add(cursor)
            cursor.state = "idle"
            if complete:
                cursor.last_success_at = now
                cursor.detail = None
            else:
                cursor.detail = "stopped early: fetch budget exhausted"
    except Exception:
        logger.exception("%s: could not clear the run lock; the stale timeout will reclaim it", cursor_name)


def release_lock_as_error(error: BaseException, cursor_name: str = CURSOR_NAME) -> None:
    """Marks the run lock as 'error' so the next pass may run immediately
    instead of waiting out the stale-lock timeout.

    Swallows its own failures on purpose: this opens a fresh session, and
    if the database is what failed in the first place, raising here would
    strand the lock AND bury the original error under this one. A stale
    lock is recovered by the timeout; a lost traceback is not."""
    try:
        with get_background_db() as db:
            cursor = load_cursor(db, cursor_name=cursor_name)
            if cursor is None:
                cursor = MlOpsSyncCursor(name=cursor_name)
                db.add(cursor)
            cursor.state = "error"
            cursor.detail = str(error)[:500]
    except Exception:
        logger.exception("%s: could not release the run lock; the stale timeout will reclaim it", cursor_name)


def parse_running_since(detail: Optional[str]) -> Optional[datetime]:
    """Parses the ISO timestamp `try_acquire_run_lock` stashes in
    `cursor.detail` while `state='running'` (no dedicated column -- reuses
    the existing free-text field). Never raises: an unparsable/missing
    value is treated as "age unknown", which the caller resolves as
    stale (a lock whose age cannot be proven is not a lock worth trusting
    forever)."""
    if not detail:
        return None
    try:
        parsed = datetime.fromisoformat(detail)
    except ValueError:
        return None
    return tz_aware(parsed)


def try_acquire_run_lock(
    db, now: datetime, cursor_name: str = CURSOR_NAME, stale_timeout: timedelta = STALE_LOCK_TIMEOUT
) -> bool:
    """Sets `state='running'` for the duration of this pass, so an
    overlapping cron invocation skips instead of racing this cursor
    (finding 4). Returns False (do not run) if another pass is genuinely
    in flight; reclaims (returns True) a 'running' lock older than
    `stale_timeout`, on the assumption its owner died.

    Keyed by `cursor_name`: the sweep (`'sweep'`) and the backfill
    (`'backfill'`) each hold their OWN row/lock, so they never block each
    other -- both may run concurrently, safely, because both converge on
    the same idempotent `upsert_order` (design D5).

    `stale_timeout` is parameterised (default `STALE_LOCK_TIMEOUT`, tuned
    for the 10-minute sweep) so a caller whose own pass legitimately runs
    much longer -- the backfill, see `backfill_service.py` -- can supply a
    timeout appropriate to ITS runtime instead of inheriting one tuned for
    a different job. Post-review fix: reusing the sweep's 30-minute
    timeout unmodified let a second invocation reclaim a live multi-hour
    backfill's lock out from under it."""
    # `SELECT ... FOR UPDATE` locks an existing row, not the gap where one
    # would go, so on a cold start two simultaneous runs both read None and
    # both INSERT -- one of them dying on the primary key. Seeding the row
    # first (idempotently) means the FOR UPDATE below always has something
    # real to lock.
    ensure_cursor_row(db, cursor_name=cursor_name)
    cursor = load_cursor(db, for_update=True, cursor_name=cursor_name)
    if cursor is None:  # pragma: no cover -- ensure_cursor_row just created it
        db.add(MlOpsSyncCursor(name=cursor_name, state="running", detail=now.isoformat()))
        return True

    if cursor.state == "running":
        running_since = parse_running_since(cursor.detail)
        if running_since is not None and (now - running_since) < stale_timeout:
            return False
        logger.warning(
            "%s: reclaiming a stale 'running' lock (detail=%r) -- a previous run likely died",
            cursor_name,
            cursor.detail,
        )

    cursor.state = "running"
    cursor.detail = now.isoformat()
    return True


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
        acquired = try_acquire_run_lock(db, now)
        if not acquired:
            logger.info("sync_ml_orders_ops: another sweep run is already in flight, skipping this pass")
            return SweepResult(ran=False, error="already running")
        cursor = load_cursor(db)
        prior_window_to = tz_aware(cursor.window_to) if cursor is not None else None

    window_start = (prior_window_to - CURSOR_OVERLAP) if prior_window_to is not None else window_from_floor
    if window_start < window_from_floor:
        window_start = window_from_floor
    window_end = now

    result = SweepResult(ran=True, window_from=window_start, window_to=prior_window_to)
    last_checkpoint_to = prior_window_to
    pending: List[Dict[str, Any]] = []
    # Budget for the page walk and the `get_shipment` lookups. No longer
    # the pass's only ceiling: `PASS_TIME_BUDGET` cuts on the clock before
    # the stale lock -- which is what this comment protected back when
    # counting calls was enough. See the note on `PASS_DEADLINE_MARGIN`.
    fetch_budget: List[int] = [MAX_WINDOW_FETCHES_PER_PASS]
    # A SEPARATE per-pass allowance for `get_shipment_costs` (see
    # `MAX_COST_FETCHES_PER_PASS`): sharing `fetch_budget` would let a
    # first-pass backlog of thousands of unsynced shipments starve the page
    # walk / `get_shipment` of their own budget on that same pass.
    cost_budget: List[int] = [MAX_COST_FETCHES_PER_PASS]
    # A THIRD separate allowance for `get_payment` (corte 5) -- same
    # starvation concern as `cost_budget`.
    payment_budget: List[int] = [MAX_PAYMENT_FETCHES_PER_PASS]
    # The pass's clock: `PASS_TIME_BUDGET` is measured against this.
    pass_started_at = datetime.now(timezone.utc)

    def _flush_pending() -> None:
        nonlocal pending
        if pending:
            process_batch(
                pending, window_from_floor, result, fetch_budget, cost_budget, pass_started_at, payment_budget
            )
            pending = []

    failure: Optional[BaseException] = None

    try:
        for event in iter_window_events(
            int(resolved_seller_id), window_start, window_end, fetch_budget, pass_started_at
        ):
            kind = event[0]
            if kind == "page":
                pending.extend(event[1])
                while len(pending) >= BATCH_SIZE:
                    process_batch(
                        pending[:BATCH_SIZE],
                        window_from_floor,
                        result,
                        fetch_budget,
                        cost_budget,
                        pass_started_at,
                        payment_budget,
                    )
                    pending = pending[BATCH_SIZE:]
            elif kind == "budget_exhausted":
                # Stop this pass without advancing past the unfinished
                # region. Whatever leaves already checkpointed are kept, so
                # the next pass resumes there instead of starting over.
                _, leaf_from, leaf_to = event
                result.budget_exhausted = True
                logger.warning(
                    "sync_ml_orders_ops: fetch budget of %s spent before reaching [%s, %s); "
                    "stopping this pass, next run resumes from the last checkpoint",
                    MAX_WINDOW_FETCHES_PER_PASS,
                    leaf_from.isoformat(),
                    leaf_to.isoformat(),
                )
                break
            elif kind == "unenumerable":
                _, leaf_from, leaf_to = event
                with get_background_db() as db:
                    record_unenumerable_window(db, leaf_from, leaf_to)
                result.windows_unenumerable += 1
            elif kind == "checkpoint":
                _, leaf_to = event
                _flush_pending()
                with get_background_db() as db:
                    cursor = load_cursor(db)
                    if cursor is None:
                        cursor = MlOpsSyncCursor(name=CURSOR_NAME, state="running")
                        db.add(cursor)
                    cursor.window_from = window_start
                    cursor.window_to = leaf_to
                    # `window_to` is this pass's PROGRESS. `last_success_at`
                    # is not written here: it means "a whole pass finished",
                    # and stamping it per leaf let a sweep that dies on a
                    # later leaf keep refreshing its own freshness signal
                    # forever -- an alert on "no success in N minutes" would
                    # never fire while the sweep was broken.
                    # state intentionally left as 'running' here -- it only
                    # flips to idle/error once the WHOLE pass finishes.
                last_checkpoint_to = leaf_to
        # Inside the try on purpose: `budget_exhausted` breaks out with up
        # to BATCH_SIZE-1 orders still buffered, and this flush writes them.
        _flush_pending()
    except WindowFetchError as e:
        logger.error("sync_ml_orders_ops: window fetch failed, cursor NOT advanced past the last completed leaf: %s", e)
        failure = e
        result.error = str(e)
    except Exception as e:  # noqa: BLE001
        # Not just WindowFetchError. Closing each individual path that could
        # strand the run lock has failed three times now, so the release is
        # guaranteed by structure instead: whatever happens above, the
        # `finally` below runs.
        logger.exception("sync_ml_orders_ops: sweep failed unexpectedly, releasing the run lock")
        failure = e
        result.error = f"{type(e).__name__}: {e}"
    finally:
        if failure is not None:
            release_lock_as_error(failure)
        else:
            release_lock_as_idle(now, complete=not result.budget_exhausted)

    result.window_to = last_checkpoint_to
    return result
