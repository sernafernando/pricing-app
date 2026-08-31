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
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_orders_ops import UNENUMERABLE_KIND, MlOpsDivergence, MlOpsSyncCursor
from app.services.ml_orders_ingestion.ingestion_service import UpsertOutcome, upsert_order
from app.services.ml_orders_ingestion.mapper import MappingError, map_order
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

# A 'running' lock older than this is assumed to belong to a dead process
# and is reclaimed rather than blocking the sweep forever. Well above the
# 10-minute cron cadence so a legitimately slow (e.g. cold-start) pass is
# never mistaken for a stale one.
STALE_LOCK_TIMEOUT = timedelta(minutes=30)

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
) -> Iterator[Tuple[str, Any]]:
    if budget is None:
        budget = [MAX_WINDOW_FETCHES_PER_PASS]
    if budget[0] <= 0:
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
        yield from iter_window_events(seller_id, date_from, midpoint, budget)
        yield from iter_window_events(seller_id, midpoint, date_to, budget)
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


def process_batch(raw_orders: List[Dict[str, Any]], window_from_floor: datetime, result: SweepResult) -> None:
    """Upserts one bounded batch in its OWN short-lived session. No HTTP
    call happens inside this block -- every raw order was already fetched
    during the (HTTP-only) search phase.

    Counters accumulate in locals and are folded into `result` only once
    the session exits cleanly. Incrementing `result` row by row inside the
    block would report writes that a rollback had undone -- the same
    "metric that lies by construction" this function already guards
    against in its DISABLED branch."""
    seen = upserted = skipped_stale = mapping_error = out_of_window = 0

    with get_background_db() as db:
        for raw_order in raw_orders:
            seen += 1
            mapped = map_order(raw_order)
            if isinstance(mapped, MappingError):
                mapping_error += 1
                logger.warning("sweep: mapping error for a search result: %s", mapped.reason)
                continue

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

    result.orders_seen += seen
    result.orders_upserted += upserted
    result.orders_skipped_stale += skipped_stale
    result.orders_mapping_error += mapping_error
    result.orders_out_of_window += out_of_window


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

    def _flush_pending() -> None:
        nonlocal pending
        if pending:
            process_batch(pending, window_from_floor, result)
            pending = []

    failure: Optional[BaseException] = None

    try:
        for event in iter_window_events(int(resolved_seller_id), window_start, window_end):
            kind = event[0]
            if kind == "page":
                pending.extend(event[1])
                while len(pending) >= BATCH_SIZE:
                    process_batch(pending[:BATCH_SIZE], window_from_floor, result)
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
