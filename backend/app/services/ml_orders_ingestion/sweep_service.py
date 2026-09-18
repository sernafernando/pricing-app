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

Deferred payment recheck (ml-ventas-repreguntar-pagos-diferido):
`payments_recheck_at` is a re-ask scheduled after a payment sync, for the
order whose `date_last_updated` STOPS MOVING (ML can finish reversing a
charge without ever touching it -- the production incident this closes).
`_run_deferred_payments_rechecks` selects due orders straight from
`MlOrdersOps`, once per pass, independent of whatever `search_orders`
returned for this pass's window -- the window gate alone would never see
an order that no longer falls inside it. The mark is cleared in exactly
two cases: the re-ask SEALED every one of the order's payment ids, or it
ran out of attempts and was given up on.
`_settle_payments_recheck` is the single place that decides the mark's
fate -- cleared on a seal, left untouched when the pass never reached
the order, pushed forward on a real unsealed attempt, and given up on
after `MAX_RECHECK_ATTEMPTS` -- and BOTH the deferred pass and the in-window
gate route through it, so the DECISION cannot drift between them --
the two still differ in what they feed it (the in-window gate seals on a
missing `payments` key, the deferred pass does not). `payments_synced_at`
is never reset to NULL by a reseal and so provides no fallback retry gate
on its own.
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
from app.services.ml_ventas_desglose.deducciones import refrescar_total_gauss_pendientes
from app.services.ml_orders_ingestion.ingestion_service import (
    QuarantineRetryResult,
    UpsertOutcome,
    retry_quarantined_orders,
    upsert_order,
    upsert_shipment,
)
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

# ml-ventas-repreguntar-pagos-diferido: how long after a payment sync we
# schedule an explicit ONE-TIME re-ask (see `MlOrdersOps.payments_recheck_at`
# for the production incident this closes). A first estimate, deliberately
# named rather than inlined at the call site so it can be found and tuned
# once the repair script (`app/scripts/repair_deferred_refunds.py`) reports
# how many charges its re-fetch actually changed.
RECHECK_AFTER = timedelta(minutes=60)

# Upper bound on how many times an order may be re-asked. Without it a
# payment that never seals -- an id ML deleted, a permanently malformed
# payload -- is re-fetched every RECHECK_AFTER forever, spending real
# budget on an answer that is never coming.
#
# Counted in ATTEMPTS, never in elapsed time. Any age-based cutoff is
# measured from a date that predates the recheck (the order's own), so an
# order already older than the cutoff when its FIRST recheck comes due
# would be abandoned with zero retries -- a bound meant to stop an
# endless retry granting none at all. Attempts are what is actually being
# bounded, so attempts are what is counted.
MAX_RECHECK_ATTEMPTS = 5

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
    # 2026-09-14 incident (per-order write isolation + quarantine):
    # `orders_write_error` is THIS pass's own write failures;
    # `orders_quarantine_recovered`/`orders_quarantine_still_failed` are
    # the automatic retry's outcome against the BACKLOG from every past
    # pass, run once at the top of this one (see `run_sweep`).
    orders_write_error: int = 0
    orders_quarantine_recovered: int = 0
    orders_quarantine_still_failed: int = 0
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
    attempted_out: Optional[set] = None,
    deadline: Optional[datetime] = None,
) -> Dict[int, Dict[str, Any]]:
    """Fetches every `order.payments[].id` on `raw_orders`, entirely
    BEFORE any DB session opens (same HTTP-before-write discipline as
    `_fetch_shipments` -- design D8).

    Fail-open per payment, same discipline as `_fetch_shipments` and
    `_sync_shipment_costs`: one failed fetch is logged and skipped, never
    raised, so a single flaky payment lookup never turns into a
    `WindowFetchError` that discards an otherwise-good batch.

    `attempted_out`, when given, collects every payment id this call
    actually SPENT A REQUEST ON. An id absent from the returned dict is
    ambiguous on its own -- it can mean the fetch failed, or it can mean
    the budget/deadline ran out before the id was ever reached, and the
    two deserve opposite treatment by a caller deciding whether an order
    was given its chance. This set is the only thing that tells them
    apart.

    `deadline`, when given, is an EARLIER cutoff than the pass's own and
    applies to these HTTP calls. A caller that only owns a slice of the
    pass (the deferred recheck) needs the slice enforced HERE: this loop
    is where the wall-clock actually goes, one slow `get_payment` at a
    time. Bounding only the caller's later bookkeeping loop bounds
    nothing, because that part is cheap.
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
            if deadline is not None and datetime.now(timezone.utc) >= deadline:
                logger.warning("sweep: this caller's time slice ran out before every payment was read")
                return payments
            if budget[0] <= 0:
                logger.warning("sweep: payment-fetch budget spent before every payment was read; the next pass resumes")
                return payments
            budget[0] -= 1
            if attempted_out is not None:
                attempted_out.add(payment_id)
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
        # `payments_recheck_at` is scheduled ONLY the first time this
        # order's payments are sealed (its `payments_synced_at` was still
        # NULL) -- a later reseal (triggered by the order's own
        # `ml_last_updated` moving again, or by the recheck gate itself)
        # must NOT push the recheck window out again, or an order could
        # defer its one-time re-ask forever by staying "stale" on every
        # pass.
        was_synced_before = db.query(MlOrdersOps.payments_synced_at).filter(MlOrdersOps.order_id == order_id).scalar()
        update_values: Dict[str, Any] = {"payments_synced_at": datetime.now(timezone.utc)}
        if was_synced_before is None:
            update_values["payments_recheck_at"] = datetime.now(timezone.utc) + RECHECK_AFTER
        db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).update(update_values)
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


def _orders_due_for_payments_recheck(order_ids: List[int]) -> dict:
    """Orders whose deferred payment re-ask is due (`payments_recheck_at
    <= now()`), in one query -- the THIRD payment-candidate gate
    (ml-ventas-repreguntar-pagos-diferido), independent of the other two:
    an order becomes a candidate here even though it is NOT stale and its
    payments already ARE synced, because ML itself may have finished
    processing a reversal (e.g. a Flex shipping-fee refund) after our
    last fetch without ever touching the order's own `ml_last_updated`
    (see the module docstring's production incident). The caller clears
    `payments_recheck_at` back to NULL once the recheck SEALS -- not
    merely once it runs -- so this gate can fire again for the same order until it seals or
    runs out of attempts.

    Returns `{order_id: payments_recheck_attempts}` and not a bare set
    of ids: the attempt count is what bounds the retry, and reading it
    here saves the caller a second query."""
    if not order_ids:
        return {}
    with get_background_db() as db:
        rows = (
            db.query(MlOrdersOps.order_id, MlOrdersOps.payments_recheck_attempts)
            .filter(
                MlOrdersOps.order_id.in_(order_ids),
                MlOrdersOps.payments_recheck_at.isnot(None),
                MlOrdersOps.payments_recheck_at <= datetime.now(timezone.utc),
            )
            .all()
        )
    return {order_id: attempts or 0 for order_id, attempts in rows}


def _deferred_pass_deadline(pass_started_at: Optional[datetime]) -> Optional[datetime]:
    """A cutoff for the deferred recheck alone: half of what the pass has
    left when it starts.

    The recheck runs BEFORE the page walk and shares the pass's deadline
    with it. Capping only the request count does not bound wall-clock --
    a handful of slow `get_payment` calls can consume the whole pass --
    and the window's own orders would then never be ingested at all. A
    late recheck is a smaller failure than an ingestion that never ran,
    so the exceptional path gets a slice, not the lot.
    """
    if pass_started_at is None:
        return None
    full_deadline = pass_started_at + PASS_TIME_BUDGET
    remaining = full_deadline - datetime.now(timezone.utc)
    if remaining <= timedelta(0):
        return datetime.now(timezone.utc)
    return datetime.now(timezone.utc) + remaining / 2


def _recheck_was_attempted(raw_order: Dict[str, Any], attempted_ids: set) -> bool:
    """Whether this order got its turn at the payment fetch.

    True when ANY of its payment ids was really requested, AND when it
    has no payment ids at all: an order with nothing to ask was
    not skipped, it was answered. Collapsing those two into the `any()`
    alone makes an empty/malformed payload look like budget exhaustion,
    and such a row then never clears, never reschedules and never counts
    an attempt -- it sits at the head of the oldest-due-first queue
    forever, costing no budget and crowding real orders out of the LIMIT.
    """
    order_payment_ids = _extract_payment_ids(raw_order)
    if not order_payment_ids:
        return True
    # ANY id, not every: a partial fetch DOES spend an attempt, because
    # the pass really spent requests on this order.
    #
    # Requiring every id looks fairer and is a trap. An order with more
    # payment ids than the deferred share -- or one the deadline always
    # cuts off midway -- can never be fetched in full. It is first in the
    # oldest-due-first queue, so every pass spends the whole share
    # re-fetching its same leading ids, judges it "not attempted", leaves
    # its mark untouched, and starts over. It never reaches
    # MAX_RECHECK_ATTEMPTS, never leaves the head of the queue, and every
    # other due order behind it is starved for good: the exact endless
    # retry and head-of-line blocking the attempt counter exists to stop.
    #
    # So the rule is progress over fairness. An order too big or too slow
    # to complete burns its attempts and is retired, which is the right
    # outcome: it is telling us it cannot be answered this way. The cost
    # is that a few budget-starved passes can retire an order that a
    # calmer pass would have sealed -- bounded, visible in the give-up
    # warning, and far cheaper than a queue that never moves again.
    return any(pid in attempted_ids for pid in order_payment_ids)


def _settle_payments_recheck(
    db,
    order_id: int,
    *,
    sealed: bool,
    attempted: bool,
    attempts_so_far: int,
    now: datetime,
    source: str,
) -> None:
    """Decides what happens to one order's `payments_recheck_at` after a
    re-ask, and is the SINGLE place that decision lives -- both the
    standalone deferred pass and `process_batch`'s in-window gate call it,
    so the two can never drift into treating the same situation
    differently.

    Four outcomes, and the distinction between the first two is the whole
    point:

    - NOT ATTEMPTED (`attempted` False): the payment budget or the pass
      deadline ran out before this order's ids were ever requested. The
      order did not fail, it never got its turn -- so the mark is left
      exactly as it is, still due, and the next pass picks it up
      immediately. Pushing it forward here would punish an order for the
      sweep's own budgeting and, worse, would report a failure that never
      happened.
    - SEALED: every payment id resolved. The mark is cleared; the re-ask
      is finished.
    - OUT OF ATTEMPTS: still not sealed after `MAX_RECHECK_ATTEMPTS`
      real attempts. The mark is cleared and the giving-up is logged. An
      hourly retry with no end is not a retry policy, it is a leak.
    - OTHERWISE: attempted, not sealed, not exhausted -- pushed forward
      by `RECHECK_AFTER`. The retry is preserved, but the order stops
      being due on every single pass, which would starve every other due
      order of the shared payment budget and can double-fetch the same
      order within one pass (the deferred pass and the in-window gate are
      independent of each other).
    """
    if not attempted:
        logger.info(
            "sweep: %s payments recheck never reached order_id=%s (budget/deadline); mark left due",
            source,
            order_id,
        )
        return
    if sealed:
        # The counter resets with the mark: a FUTURE re-ask for this order
        # is a new question, and must get its full allowance rather than
        # inheriting the attempts an already-answered one happened to use.
        db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).update(
            {"payments_recheck_at": None, "payments_recheck_attempts": 0}
        )
        return
    attempts = (attempts_so_far or 0) + 1
    if attempts >= MAX_RECHECK_ATTEMPTS:
        # The counter is RESET along with the mark, exactly as on a seal.
        # Leaving it at its exhausted value would make the next re-ask
        # scheduled for this order -- a new question, after a later
        # payment sync -- start already out of attempts and be retired on
        # its first pass. Giving up on one question must not disqualify
        # the next.
        db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).update(
            {"payments_recheck_at": None, "payments_recheck_attempts": 0}
        )
        logger.warning(
            "sweep: %s payments recheck giving up on order_id=%s after %s of %s allowed attempts without sealing",
            source,
            order_id,
            attempts,
            MAX_RECHECK_ATTEMPTS,
        )
        return
    next_recheck_at = now + RECHECK_AFTER
    db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).update(
        {"payments_recheck_at": next_recheck_at, "payments_recheck_attempts": attempts}
    )
    logger.warning(
        "sweep: %s payments recheck did not seal for order_id=%s, rescheduled to %s",
        source,
        order_id,
        next_recheck_at.isoformat(),
    )


def _run_deferred_payments_rechecks(
    result: SweepResult,
    payment_budget: List[int],
    pass_started_at: Optional[datetime],
    seller_id: int,
) -> None:
    """Runs the deferred payment re-ask (ml-ventas-repreguntar-pagos-
    diferido) ONCE per pass, straight from `MlOrdersOps` -- independent of
    whatever this pass's `search_orders` window happens to return.

    `_orders_due_for_payments_recheck` as used inside `process_batch` only
    ever sees `in_window_ids`, the batch the page walk's search window
    produced. `RECHECK_AFTER` is far longer than `CURSOR_OVERLAP` (see
    both constants) -- by the time a recheck is due, the order this
    feature exists for
    (one whose `date_last_updated` STOPPED MOVING, see the module
    docstring's production incident) has long fallen out of every later
    window and `process_batch` never receives it again. The mark would
    sit in the database forever. This function selects due orders
    directly instead, so the re-ask fires regardless of what the search
    returned.

    The query is scoped to `seller_id`, ordered by `payments_recheck_at`
    ascending (oldest-due first, FIFO), and excludes rows with no
    `raw_order` payload at the SQL level -- all three matter together
    with `LIMIT`: an unordered or unscoped query can keep returning the
    same subset across passes and starve the rest, and a NULL-payload row
    (nothing this recheck could ever act on) must not consume a slot of
    the LIMIT that a real due order needed.

    No `get_order` re-fetch is needed: `MlOrdersOps.raw_order` already
    holds the payload from the order's last successful ingestion, and
    that is where `order.payments[].id` -- the only thing this recheck
    needs -- already lives. Only the payment fetch itself goes over HTTP,
    which is what actually answers whether ML reversed something.

    Bounded by SPEND, not by row count. This pass runs before the page
    walk and shares one budget with it, so it takes a share (half) and
    fetches against its OWN budget list, charging back only what it
    actually spent. Capping rows instead would bound nothing: a single
    order can carry any number of payment ids and each id costs one
    request, so one row could still drain everything the window's own
    orders need."""
    if payment_budget[0] <= 0 or _pass_deadline_reached(pass_started_at):
        return
    # This pass runs BEFORE the page walk and shares one payment budget
    # with it. Left unbounded, a backlog of due rechecks consumes the
    # entire budget and the window's own freshly-arrived orders get no
    # payment sync at all -- the ordinary path starved by the exceptional
    # one. So it takes half, rounded DOWN (see the floor note below).
    #
    # The cap is on the SPEND, not on the row count: capping rows alone
    # bounds nothing, because a single order can carry any number of
    # payment ids and `_fetch_payments` charges one request per id. So
    # the fetch below runs against its OWN budget list, and only what it
    # actually spent is charged back to the shared one.
    # Plain halving, with NO `max(1, ...)` floor. A floor of one defeats
    # the sharing exactly where it matters most: with a single request
    # left, it hands the whole remainder to the exceptional path and
    # leaves the window's own freshly-arrived orders with nothing. A
    # recheck can wait a pass; an order that never gets ingested cannot.
    deferred_share = payment_budget[0] // 2
    if deferred_share <= 0:
        return
    # A share of the pass's TIME as well as of its requests. Bounding
    # only the request count leaves this pass free to burn the entire
    # deadline before the page walk ever starts -- slow responses, not
    # many of them, are enough. The window's own orders would then never
    # be ingested at all, which is a worse outage than a late recheck.
    deferred_deadline = _deferred_pass_deadline(pass_started_at)
    now = datetime.now(timezone.utc)
    with get_background_db() as db:
        due_rows = (
            db.query(
                MlOrdersOps.order_id,
                MlOrdersOps.raw_order,
                MlOrdersOps.payments_recheck_attempts,
            )
            .filter(
                MlOrdersOps.seller_id == seller_id,
                MlOrdersOps.payments_recheck_at.isnot(None),
                MlOrdersOps.payments_recheck_at <= now,
                MlOrdersOps.raw_order.isnot(None),
            )
            .order_by(MlOrdersOps.payments_recheck_at.asc())
            # The request share doubles as the ROW limit because an order
            # normally costs at least one request, so selecting more rows
            # than requests could be paid for is pointless. It is only a
            # selection bound: the real cap on spend is `deferred_budget`
            # below. (An order with no payment ids costs nothing and still
            # takes a row -- it is settled without any request.)
            .limit(deferred_share)
            .all()
        )
    due_orders = list(due_rows)
    if not due_orders:
        return
    attempted_ids: set = set()
    # A SEPARATE budget list, seeded with this pass's share. Handing
    # `payment_budget` straight through would let these fetches spend
    # everything the window's own orders still need.
    deferred_budget = [deferred_share]
    payments_payload = _fetch_payments(
        [raw_order for _, raw_order, _ in due_orders],
        deferred_budget,
        started_at=pass_started_at,
        attempted_out=attempted_ids,
        deadline=deferred_deadline,
    )
    # Charge back exactly what was spent, so the shared budget stays an
    # honest count of the requests this pass has made.
    payment_budget[0] -= deferred_share - deferred_budget[0]
    synced = 0
    with get_background_db() as db:
        for order_id, raw_order, attempts_so_far in due_orders:
            # ONLY the pass deadline here, never `deferred_deadline`: the
            # slice bounds the FETCH, where the wall-clock goes. Checking
            # it again in this cheap loop is a livelock -- time only moves
            # forward, so whenever the fetch stopped on the slice this
            # loop would break before settling anything, discarding every
            # payment already paid for in requests and counting no
            # attempt. The next pass would repeat it identically. Persist
            # what was bought.
            if _pass_deadline_reached(pass_started_at):
                break
            try:
                # INSIDE the try: this reads the STORED payload, so a
                # malformed one can make the check itself raise. Computed
                # outside, that would abort the whole remaining loop and
                # take every order behind this one down with it --
                # discarding payments already paid for in requests. The
                # per-order isolation has to cover everything that touches
                # this order's data, not just the DB write.
                #
                # Did this order's payments actually get requested? An id
                # missing from `payments_payload` alone cannot answer that
                # (see `_fetch_payments`'s `attempted_out`), and the answer
                # decides whether the mark moves at all.
                attempted = _recheck_was_attempted(raw_order, attempted_ids)
                # `raw_order` here is the STORED payload, not guaranteed
                # fresh off ML (it may predate this exact sweep version)
                # -- the same reasoning `sync_payments_for_order`'s own
                # docstring gives for the backfill script, so
                # `missing_key_is_empty` stays at its default False: an
                # absent `payments` key leaves the seal unwritten rather
                # than sealing on an unknown, and the unsealed result is
                # then settled by `_settle_payments_recheck` like any
                # other.
                order_synced, sealed = sync_payments_for_order(db, order_id, raw_order, payments_payload)
                _settle_payments_recheck(
                    db,
                    order_id,
                    sealed=sealed,
                    attempted=attempted,
                    attempts_so_far=attempts_so_far,
                    now=now,
                    source="deferred",
                )
                # COMMIT PER ORDER, and roll back on failure. Both halves
                # matter: `get_background_db` commits once, at block exit,
                # so without this an error on the LAST order would discard
                # every earlier order's work; and a failure that happened
                # during a FLUSH leaves the Session in a state where every
                # later statement raises PendingRollbackError, so catching
                # the exception without rolling back isolates nothing --
                # the very next order dies too, and so does the final
                # commit. (A failed SELECT does not poison the Session; a
                # failed flush does. The rollback covers both.)
                db.commit()
                # Counted only AFTER the commit that makes it true. Adding
                # it before would credit work that a failed commit then
                # rolled back, and `payments_synced` is reported as a
                # count of rows actually written.
                synced += order_synced
            except Exception:  # noqa: BLE001
                db.rollback()
                logger.exception(
                    "sweep: deferred payments recheck failed for order_id=%s; continuing with remaining orders",
                    order_id,
                )
                # The mark MUST move even here. FIFO order means an order
                # that reliably explodes would otherwise stay at the head
                # of the queue forever, be selected first on every pass,
                # and crash the same way -- blocking every order behind it
                # (head-of-line). Rescheduling it is what keeps one
                # poisoned row from becoming a permanent outage of the
                # whole re-ask.
                #
                # Done on its OWN SESSION, not on `db`. `db` is the
                # session the failure just happened on: a rollback clears
                # the failed transaction but the connection can still be
                # the thing that broke (a dropped connection, a statement
                # timeout, a poisoned pool entry), in which case this
                # rescue write fails too -- and then the mark never moves
                # and the head-of-line blockage this whole branch exists
                # to prevent comes right back. A fresh session is the
                # only way for the rescue not to depend on whatever broke.
                try:
                    with get_background_db() as rescue_db:
                        _settle_payments_recheck(
                            rescue_db,
                            order_id,
                            sealed=False,
                            # DELIBERATE, and not the same assumption that
                            # `_recheck_was_attempted` exists to avoid: a
                            # crash IS a spent attempt. The pass took this
                            # order's turn and burned it. Passing the
                            # measured value here would leave an order that
                            # both crashes AND was never fetched sitting at
                            # the head of the oldest-due-first queue,
                            # exploding identically on every future pass --
                            # the head-of-line outage this except branch
                            # exists to prevent. Counting it is also what
                            # eventually retires it via MAX_RECHECK_ATTEMPTS.
                            attempted=True,
                            attempts_so_far=attempts_so_far,
                            now=now,
                            source="deferred(failed)",
                        )
                except Exception:  # noqa: BLE001
                    # Nothing left to try. Logged as an ERROR and not
                    # swallowed quietly: this order WILL be picked first
                    # again next pass and may block the queue, and that
                    # has to be visible rather than inferred from a
                    # recheck that mysteriously stops making progress.
                    logger.exception(
                        "sweep: could not reschedule the failed recheck for order_id=%s; "
                        "it stays at the head of the due queue",
                        order_id,
                    )
    result.payments_synced += synced


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
            # Stored BEFORE the usability check, and deliberately also on
            # the branch that gives up below: "ML answered but the costs
            # were not settled yet" and "we never asked" are different
            # facts, and with only the two numeric columns they looked
            # identical. The payload is what tells them apart -- and it
            # carries `senders[0].compensation`, where money ML pays the
            # seller for a Flex shipment would appear.
            row.raw_costs = payload
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
    seen = upserted = skipped_stale = mapping_error = out_of_window = write_error = 0

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
    # Third gate (ml-ventas-repreguntar-pagos-diferido): an order whose
    # deferred re-ask is due becomes a payment candidate REGARDLESS of the
    # other two triggers -- it may be neither stale nor unsynced, and
    # still need re-fetching because ML processed a reversal after our
    # last look without moving `ml_last_updated` (see module docstring).
    recheck_attempts_by_order = _orders_due_for_payments_recheck(in_window_ids)
    recheck_due_ids = set(recheck_attempts_by_order)
    payment_candidates = [
        (raw_order, mapped)
        for raw_order, mapped in in_window
        if mapped.order_id in stale_trigger_ids
        or mapped.order_id not in payments_already_synced
        or mapped.order_id in recheck_due_ids
    ]
    in_window_attempted_ids: set = set()
    payments_payload = _fetch_payments(
        [raw for raw, _ in payment_candidates],
        payment_budget,
        started_at=pass_started_at,
        attempted_out=in_window_attempted_ids,
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
            elif outcome == UpsertOutcome.WRITE_ERROR:
                # Quarantined + surfaced as an `ingest_failed` divergence
                # already inside `upsert_order` -- this counter is ONLY
                # for this pass's own visibility (2026-09-14 incident),
                # never the recovery path itself (see `run_sweep`'s
                # `retry_quarantined_orders` call at the top of the pass).
                write_error += 1
                logger.error("sweep: write error for order_id=%s — quarantined for automatic retry", mapped.order_id)
                # The order row was rolled back to its pre-write state (or
                # never existed) -- syncing payments/shipment for it now
                # would write child rows for a parent that may not be
                # there.
                #
                # The automatic retry re-attempts the ORDER, and NOT its
                # payments: `retry_quarantined_orders` makes zero HTTP
                # calls by design, and fetching payments needs one. A
                # recovered order therefore lands with `payments_synced_at`
                # still NULL, which IS the existing retry gate -- the next
                # sweep pass that sees it in its window fetches them.
                #
                # Until that happens the sale is NOT silent: with no
                # payments its breakdown reports `payments_not_synced` and
                # its `neto` is None, never a zero pretending to be money.
                #
                # RESIDUAL, named rather than left to be discovered: an
                # order that stays quarantined longer than the sweep's own
                # window will not be re-swept once recovered, so its
                # payments would stay unfetched. Today quarantine is
                # measured in hours; if it ever is not, that gap needs its
                # own pass.
                continue
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
                # seal.
                if raw_order.get("payments") is None:
                    _record_payments_key_missing(db, mapped.order_id)
                order_synced, sealed = sync_payments_for_order(
                    db, mapped.order_id, raw_order, payments_payload, missing_key_is_empty=True
                )
                payments_synced += order_synced

                # The mark's fate goes through the SAME helper the
                # standalone deferred pass uses, so this gate and that one
                # can never disagree about what a seal, a partial result
                # or an exhausted retry means.
                #
                # `attempted` is MEASURED here, never assumed. Being a
                # payment candidate only means this order was handed to
                # `_fetch_payments`; that call stops early when the budget
                # or the deadline runs out, so the orders at the tail of a
                # large batch can reach this line without a single request
                # having been made for them. Hardcoding True would
                # reschedule them as if they had failed -- the same lie
                # the deferred pass already refuses to tell.
                if mapped.order_id in recheck_due_ids:
                    _settle_payments_recheck(
                        db,
                        mapped.order_id,
                        sealed=sealed,
                        attempted=_recheck_was_attempted(raw_order, in_window_attempted_ids),
                        attempts_so_far=recheck_attempts_by_order.get(mapped.order_id, 0),
                        now=datetime.now(timezone.utc),
                        source="in-window",
                    )

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
    result.orders_write_error += write_error
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
        # Automatic quarantine retry -- BEFORE processing anything new
        # (2026-09-14 incident): re-attempts every previously write-failed
        # order from its stored raw payload, zero HTTP calls. This is what
        # heals the data on its own the day a fix ships, with nobody
        # running anything by hand.
        #
        # INSIDE this `try`, and in its OWN session, on purpose. The lock is
        # taken further up, in a block whose COMMIT lands outside every
        # try/finally; while that block only held the lock and a SELECT its
        # commit was trivial, but carrying up to fifty upserts, deletes and
        # divergence inserts through it means a failed commit escapes and
        # strands the lock -- the exact failure that cost four days of
        # ingestion. The release is guaranteed by STRUCTURE, so this belongs
        # inside that structure.
        try:
            with get_background_db() as retry_db:
                quarantine_result = retry_quarantined_orders(retry_db)
        except Exception:  # noqa: BLE001
            logger.exception("sync_ml_orders_ops: quarantine retry failed; continuing with the pass")
            quarantine_result = QuarantineRetryResult()
        result.orders_quarantine_recovered = quarantine_result.recovered
        result.orders_quarantine_still_failed = quarantine_result.still_failed
        if quarantine_result.attempted:
            logger.warning(
                "sync_ml_orders_ops: quarantine retry — attempted=%s recovered=%s still_failed=%s",
                quarantine_result.attempted,
                quarantine_result.recovered,
                quarantine_result.still_failed,
            )

        # Materialise `total_gauss` for whatever needs it, bounded. The
        # column is a SORT KEY (design D2) and nothing else wrote it, so
        # "sort by Total Gauss" was quietly falling back to sort by id and
        # the five `marcar_stale` hooks were invalidating towards a
        # recomputation that did not exist.
        #
        # INSIDE this `try`, in its own session, for the same reason the
        # quarantine retry is: the block that takes the lock commits
        # outside every try/finally, and a failure there strands the lock.
        try:
            with get_background_db() as gauss_db:
                refrescados = refrescar_total_gauss_pendientes(gauss_db)
            if refrescados:
                logger.info("sync_ml_orders_ops: total_gauss refreshed for %s order(s)", refrescados)
        except Exception:  # noqa: BLE001
            logger.exception("sync_ml_orders_ops: total_gauss refresh failed; continuing with the pass")

        # Deferred payment recheck (ml-ventas-repreguntar-pagos-diferido):
        # run ONCE per pass, straight from the database, BEFORE the page
        # walk -- not gated on whatever `search_orders` returns for this
        # pass's window. See `_run_deferred_payments_rechecks`'s own
        # docstring for why the window-scoped gate inside `process_batch`
        # alone can never catch the order this feature exists for.
        try:
            _run_deferred_payments_rechecks(result, payment_budget, pass_started_at, int(resolved_seller_id))
        except Exception:  # noqa: BLE001
            logger.exception("sync_ml_orders_ops: deferred payments recheck failed; continuing with the pass")

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
