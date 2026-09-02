"""Historical backfill over the rolling window (slice 5 of
ml-ventas-fuente-de-verdad).

Reuses the sweep's machinery instead of duplicating it (obs #1852 lesson
1 -- "closing individual paths does not close a class" applies just as
much to writing a second copy of a class that was already closed once):
the same streaming window walk (`sweep_service.iter_window_events`), the
same bounded-batch upsert (`sweep_service.process_batch`), and the same
generic run-lock/checkpoint cursor helpers (`sweep_service.load_cursor`
et al., now parameterised by `cursor_name`). Everything below is either a
day-sized wrapper around those functions or CLI-argument parsing.

Pacing differs from the sweep on purpose (design decision for this
slice): the sweep is a 10-minute cron pass bounded by
`MAX_WINDOW_FETCHES_PER_PASS` so a single invocation always returns
promptly. A backfill is an operator-invoked, long-running walk over the
WHOLE `--days` range, expected to take many minutes. Reusing the sweep's
per-pass fetch budget as-is would silently truncate a backfill into many
"budget_exhausted" partial passes with no visible progress between them.
Instead the backfill loops one CALENDAR DAY at a time, walking BACKWARDS
from the most recent boundary to the oldest, checkpointing after each day
completes. Each day is small enough that the sweep's own per-window fetch
budget (2000 fetches) is still the right escape hatch for a single day
that is itself too dense to enumerate -- reused unchanged via
`iter_window_events`.

Own run lock, own cursor: `ml_ops_sync_cursor.name='backfill'`, entirely
separate from the sweep's `name='sweep'` row (design: `ml_ops_sync_cursor`
schema already reserves `'backfill'` in its own docstring). The two never
block each other -- both may run at the same time -- because BOTH ends of
any race converge on the exact same idempotent `upsert_order` (design D5:
`ON CONFLICT (order_id) DO UPDATE ... WHERE excluded.ml_last_updated >
ml_orders_ops.ml_last_updated`), so a duplicate fetch of the same order by
sweep and backfill is a structural no-op, never a duplicate or corrupted
row -- see `TestOverlapWithSweepIsSafe` in
`tests/services/ml_orders_ingestion/test_backfill_service.py`.

Operator visibility: `ml_ops_sync_cursor` row `name='backfill'` IS the
external progress signal -- `window_from` is the oldest boundary
completed so far (it moves backward as the run progresses), `state`
shows `running`/`idle`/`error` exactly like the sweep, and `detail` carries
either the running-since timestamp or the last error. `--dry-run` never
writes that row (a dry run's "progress" would lie to a real run that
resumes from it later), so it must be re-run without `--dry-run` from
scratch. The script entry point (`app/scripts/backfill_ml_orders_ops.py`)
logs one line per day so an operator watching the log sees measurable,
incremental progress instead of a single silent multi-hour call.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_orders_ops import MlOpsSyncCursor
from app.services.ml_orders_ingestion.mapper import MappingError, map_order
from app.services.ml_orders_ingestion.sweep_service import (
    BATCH_SIZE,
    CURSOR_NAME as SWEEP_CURSOR_NAME,
    SweepResult,
    WindowFetchError,
    ensure_cursor_row,
    iter_window_events,
    load_cursor,
    process_batch,
    record_unenumerable_window,
    release_lock_as_error,
    release_lock_as_idle,
    try_acquire_run_lock,
    tz_aware,
)

logger = logging.getLogger(__name__)

CURSOR_NAME = "backfill"

# Never reused by anything else: guards against a future refactor
# accidentally pointing the backfill at the sweep's own row. A plain
# `assert` is stripped under `python -O` and is worth nothing as a
# structural guard -- fail loudly and unconditionally instead.
if CURSOR_NAME == SWEEP_CURSOR_NAME:
    raise RuntimeError("backfill_service.CURSOR_NAME must not collide with the sweep's own cursor name")

DAY = timedelta(days=1)

# The sweep's 30-minute stale-lock timeout is tuned for its own 10-minute
# cron cadence. A backfill is an operator-invoked, long-running walk
# (module docstring: "expected to take many minutes", and in practice can
# run for hours over a wide `--days` range). Inheriting the sweep's
# timeout would let a second invocation reclaim a still-running backfill's
# lock out from under it. 12 hours comfortably covers a cold 180-day
# backfill while still recovering a genuinely dead process well within a
# single business day.
BACKFILL_STALE_LOCK_TIMEOUT = timedelta(hours=12)

_DAYS_RANGE_RE = re.compile(r"^\s*(\d+)\s*\.\.\s*(\d+)\s*$")


def parse_days_arg(value: str) -> Tuple[int, int]:
    """Parses the `--days` CLI argument. Accepts either:
    - a single int `N` -- the full width from today back to N days ago
      (`(0, N)`), matching the design doc's rollout example
      (`--days 90 --dry-run`);
    - a `FROM..TO` range -- only the historical tail between `FROM` and
      `TO` days ago (`(FROM, TO)`), matching the design doc's
      `--days 90..180` example, useful to backfill only the older part of
      the window the sweep's own cold start does not keep re-visiting.

    Raises `ValueError` for anything else, including an inverted range
    (`FROM >= TO`) -- fail loudly on a malformed operator invocation
    rather than silently backfilling zero or a negative-width window."""
    match = _DAYS_RANGE_RE.match(value)
    if match:
        days_from, days_to = int(match.group(1)), int(match.group(2))
    else:
        try:
            days_from, days_to = 0, int(value)
        except ValueError as e:
            raise ValueError(f"invalid --days value: {value!r}") from e

    if days_from < 0 or days_to < 0:
        raise ValueError(f"--days values must be non-negative: {value!r}")
    if days_from >= days_to:
        raise ValueError(f"--days range must have FROM < TO: {value!r}")
    return days_from, days_to


@dataclass
class BackfillResult:
    ran: bool
    dry_run: bool = False
    days_completed: int = 0
    orders_seen: int = 0
    orders_upserted: int = 0
    orders_skipped_stale: int = 0
    orders_mapping_error: int = 0
    orders_out_of_window: int = 0
    windows_unenumerable: int = 0
    budget_exhausted: bool = False
    # True only for a REAL (non-dry-run) pass that found the checkpoint
    # already covering the entire requested range and did zero new work
    # as a result -- distinguishes a legitimate no-op from a pass that
    # processed `days_completed` days for real (finding 4, round 3).
    already_up_to_date: bool = False
    error: Optional[str] = None


def _fold_counts(dst: BackfillResult, src: SweepResult) -> None:
    """Adds one `process_batch` call's counters into the running result.
    Called right after EACH batch, not just once at the end of the day
    (finding 2, round 3): `process_batch` commits its own session as it
    goes, so a batch that already landed in the database must be counted
    even if a LATER page in the same day raises `WindowFetchError` --
    under-reporting already-committed work is as wrong as over-reporting
    rolled-back work."""
    dst.orders_seen += src.orders_seen
    dst.orders_upserted += src.orders_upserted
    dst.orders_skipped_stale += src.orders_skipped_stale
    dst.orders_mapping_error += src.orders_mapping_error
    dst.orders_out_of_window += src.orders_out_of_window


def _dry_run_count_window(
    seller_id: int, day_from: datetime, day_to: datetime, window_from_floor: datetime
) -> tuple[int, int, int, bool]:
    """The `--dry-run` equivalent of `process_batch`: enumerates the
    window (so `search_orders` really is called and the window bounds are
    really computed, per the RED test's own promise) but never opens a DB
    session and never calls `upsert_order` -- zero writes, by construction
    rather than by a flag threaded through the write path.

    Applies the SAME window filter as the real run and returns
    `(seen, out_of_window, mapping_error, budget_exhausted)`. A preview
    that counts rows the real run would exclude, silently drops ones it
    would report, or fails to say it truncated on the fetch budget -- is
    not a preview (finding 3, round 3: parity with the real run, which
    DOES report `budget_exhausted`, extends to every field, not just the
    three this function already returned)."""
    seen = 0
    out_of_window = 0
    mapping_error = 0
    budget_exhausted = False
    for event in iter_window_events(seller_id, day_from, day_to):
        kind = event[0]
        if kind == "page":
            for raw_order in event[1]:
                seen += 1
                mapped = map_order(raw_order)
                if isinstance(mapped, MappingError):
                    mapping_error += 1
                    continue
                if mapped.date_created is not None and mapped.date_created < window_from_floor:
                    out_of_window += 1
        elif kind == "budget_exhausted":
            # `break` below, like run_sweep: draining the generator emits one
            # warning per remaining sub-window and floods the log in an
            # already-degraded run.
            budget_exhausted = True
            logger.warning(
                "backfill(dry-run): fetch budget spent before [%s, %s) finished enumerating",
                day_from.isoformat(),
                day_to.isoformat(),
            )
            break
        elif kind == "unenumerable":
            logger.warning(
                "backfill(dry-run): [%s, %s) is not enumerable even at the minimum bisect span",
                event[1].isoformat(),
                event[2].isoformat(),
            )
    logger.info(
        "backfill(dry-run): window [%s, %s) would fetch %d order(s) -- no writes performed",
        day_from.isoformat(),
        day_to.isoformat(),
        seen,
    )
    return seen, out_of_window, mapping_error, budget_exhausted


def _process_day(
    seller_id: int,
    day_from: datetime,
    day_to: datetime,
    window_from_floor: datetime,
    result: BackfillResult,
) -> bool:
    """Processes one calendar-day window for real, reusing the sweep's
    exact streaming walk + bounded-batch upsert. Raises `WindowFetchError`
    on an unresolved fetch failure (fail-closed per day, mirroring the
    sweep's fail-closed-per-window contract) -- the caller must not
    checkpoint past a day that raised.

    Returns True only if the day was FULLY enumerated. False means the
    fetch budget ran out partway through this single day: the caller must
    NOT checkpoint `window_from` past `day_from` in that case, so the next
    pass resumes and finishes this exact day instead of treating a
    partial day as done.

    `window_from_floor` is the floor of the REQUESTED RANGE, not of the day
    being walked. `process_batch` uses it to decide what falls outside the
    window, and an order created long before the day it was updated on is
    exactly what a backfill exists to fetch -- passing `day_from` here
    excluded almost everything and filed a divergence row for each."""
    pending: list = []
    day_completed = True

    def _flush() -> None:
        nonlocal pending
        if pending:
            batch_result = SweepResult(ran=True)
            process_batch(pending, window_from_floor, batch_result)
            _fold_counts(result, batch_result)
            pending = []

    for event in iter_window_events(seller_id, day_from, day_to):
        kind = event[0]
        if kind == "page":
            pending.extend(event[1])
            while len(pending) >= BATCH_SIZE:
                batch_result = SweepResult(ran=True)
                process_batch(pending[:BATCH_SIZE], window_from_floor, batch_result)
                # Folded IMMEDIATELY, not at the end of the day (finding 2,
                # round 3): `process_batch` already committed this batch in
                # its own session, so if a LATER page in this same day
                # raises `WindowFetchError`, this batch's writes must still
                # be counted -- they happened, regardless of how the day
                # as a whole ends.
                _fold_counts(result, batch_result)
                pending = pending[BATCH_SIZE:]
        elif kind == "unenumerable":
            _, leaf_from, leaf_to = event
            # Same instrumentation the sweep persists (finding 1, round
            # 3): a leaf that cannot be enumerated even at the minimum
            # bisect span leaves a `ml_ops_divergence` row, not just a
            # local counter that dies with this function's stack frame.
            with get_background_db() as db:
                record_unenumerable_window(db, leaf_from, leaf_to)
            result.windows_unenumerable += 1
            logger.warning(
                "backfill: [%s, %s) is not enumerable even at the minimum bisect span -- recorded, skipped",
                leaf_from.isoformat(),
                leaf_to.isoformat(),
            )
        elif kind == "budget_exhausted":
            # `break` below, like run_sweep: draining the generator emits one
            # warning per remaining sub-window and floods the log in an
            # already-degraded run.
            day_completed = False
            logger.warning(
                "backfill: fetch budget spent before day [%s, %s) finished; will resume this exact day next run",
                day_from.isoformat(),
                day_to.isoformat(),
            )
            break
    _flush()

    return day_completed


def run_backfill(
    days_from: int = 0,
    days_to: Optional[int] = None,
    seller_id: Optional[int] = None,
    dry_run: bool = False,
    restart: bool = False,
) -> BackfillResult:
    """Entry point for `app/scripts/backfill_ml_orders_ops.py`.

    Flag-gated exactly like the sweep: a complete no-op (zero HTTP calls,
    zero DB reads/writes) while `ML_ORDERS_OPS_ENABLED` is False.

    Walks day-sized windows BACKWARDS from `now - days_from` down to
    `now - days_to`, checkpointing `ml_ops_sync_cursor(name='backfill')`
    after each day so a killed run resumes at the last fully-completed
    day instead of restarting (see module docstring).

    `restart=True` ignores any existing checkpoint for `name='backfill'`
    and walks the entire requested range from scratch, regardless of
    whether it matches or is a subset of a previously-completed range
    (finding 4, round 3): a checkpoint whose range is EXACTLY the one
    requested again is otherwise a permanent no-op with no operator
    escape hatch short of deleting the cursor row by hand.
    """
    if not settings.ML_ORDERS_OPS_ENABLED:
        return BackfillResult(ran=False, dry_run=dry_run)

    resolved_seller_id = seller_id if seller_id is not None else settings.ML_USER_ID
    if not resolved_seller_id:
        logger.error("backfill_ml_orders_ops: ML_USER_ID not configured, backfill cannot run")
        return BackfillResult(ran=False, dry_run=dry_run, error="seller_id not configured")

    resolved_days_to = days_to if days_to is not None else settings.ML_ORDERS_OPS_WINDOW_DAYS

    now = datetime.now(timezone.utc)
    newest_boundary = now - timedelta(days=days_from)
    oldest_boundary = now - timedelta(days=resolved_days_to)
    # `--days N` asks for orders UPDATED in that span. What decides whether an
    # order is too OLD to ingest is the rolling window, exactly as in the
    # sweep. Using the requested range for both threw away every order created
    # before it -- an order created a month ago and updated yesterday is the
    # very thing a backfill is for, and it was being discarded and filed as a
    # divergence.
    window_from_floor = now - timedelta(days=settings.ML_ORDERS_OPS_WINDOW_DAYS)

    result = BackfillResult(ran=True, dry_run=dry_run)

    if dry_run:
        # Dry runs never touch the lock or the cursor: no progress is
        # persisted, so a subsequent real run is never short-circuited by
        # a dry run's own "completed" checkpoint (see module docstring).
        current_end = newest_boundary
        while current_end > oldest_boundary:
            day_start = max(current_end - DAY, oldest_boundary)
            day_seen, day_out, day_bad, day_budget_exhausted = _dry_run_count_window(
                int(resolved_seller_id), day_start, current_end, window_from_floor
            )
            result.orders_seen += day_seen
            result.orders_out_of_window += day_out
            result.orders_mapping_error += day_bad
            if day_budget_exhausted:
                # Stop where the real run stops. It breaks on the first
                # truncated day, so continuing here would preview days the
                # real run will never reach -- and the day itself was only
                # partly enumerated, so it does not count as completed.
                result.budget_exhausted = True
                break
            result.days_completed += 1
            current_end = day_start
        return result

    with get_background_db() as db:
        acquired = try_acquire_run_lock(db, now, cursor_name=CURSOR_NAME, stale_timeout=BACKFILL_STALE_LOCK_TIMEOUT)
        if not acquired:
            logger.info("backfill_ml_orders_ops: another backfill run is already in flight, skipping this pass")
            return BackfillResult(ran=False, dry_run=dry_run, error="already running")
        ensure_cursor_row(db, cursor_name=CURSOR_NAME)
        cursor = load_cursor(db, cursor_name=CURSOR_NAME)
        resume_from = tz_aware(cursor.window_from) if cursor is not None else None

    # A checkpoint belongs to whatever `[oldest_boundary, newest_boundary)`
    # range the run that left it was asked to cover. A DIFFERENT range
    # requested now (e.g. a completed `--days 90` followed by `--days 30`)
    # leaves a `resume_from` that already sits below THIS call's
    # `oldest_boundary` -- honouring it would enter the walk loop zero
    # times, report `ran=True`/`days_completed=0` and still stamp
    # `last_success_at`, exactly as if the range had really been covered.
    # Discard a resume point that falls outside the CURRENT request
    # instead of trusting it blindly; a stale/mismatched checkpoint means
    # "start this range from scratch", not "nothing to do".
    if restart:
        if resume_from is not None:
            logger.info(
                "backfill_ml_orders_ops: --restart requested, ignoring existing checkpoint window_from=%s",
                resume_from.isoformat(),
            )
        resume_from = None
    elif resume_from is not None and not (oldest_boundary <= resume_from < newest_boundary):
        logger.info(
            "backfill_ml_orders_ops: checkpoint window_from=%s is outside the requested range "
            "[%s, %s) -- ignoring it and starting this range from scratch",
            resume_from.isoformat(),
            oldest_boundary.isoformat(),
            newest_boundary.isoformat(),
        )
        resume_from = None

    current_end = resume_from if resume_from is not None else newest_boundary
    if current_end > newest_boundary:
        current_end = newest_boundary

    if resume_from is not None and current_end <= oldest_boundary:
        # The checkpoint already covers the ENTIRE requested range -- a
        # legitimate no-op, but it must be distinguishable in the result
        # from a genuine completed pass (finding 4, round 3): the
        # operator needs `--restart` to force a rerun, and the log/result
        # must say "nothing to do" rather than imply real work happened.
        result.already_up_to_date = True
        logger.info(
            "backfill_ml_orders_ops: range [%s, %s) is already fully covered by the existing checkpoint "
            "(window_from=%s) -- nothing to do; pass --restart to force a full rerun",
            oldest_boundary.isoformat(),
            newest_boundary.isoformat(),
            resume_from.isoformat(),
        )

    failure: Optional[BaseException] = None
    last_checkpoint: Optional[datetime] = resume_from

    try:
        while current_end > oldest_boundary:
            day_start = max(current_end - DAY, oldest_boundary)
            day_completed = _process_day(int(resolved_seller_id), day_start, current_end, window_from_floor, result)

            if not day_completed:
                # Partial day: do NOT checkpoint past `current_end` (the
                # start of this day), so the next pass re-does this exact
                # day instead of skipping the part it never reached.
                result.budget_exhausted = True
                logger.warning(
                    "backfill_ml_orders_ops: fetch budget exhausted mid-day, stopping this pass; "
                    "day [%s, %s) will be retried in full next run",
                    day_start.isoformat(),
                    current_end.isoformat(),
                )
                break

            result.days_completed += 1
            with get_background_db() as db:
                cursor = load_cursor(db, cursor_name=CURSOR_NAME)
                if cursor is None:
                    # The sweep's own checkpoint guards the same way. A
                    # backfill walks for hours, so an operator deleting the
                    # row mid-run would otherwise raise AttributeError and
                    # abandon the rest of the range.
                    cursor = MlOpsSyncCursor(name=CURSOR_NAME, state="running")
                    db.add(cursor)
                cursor.window_from = day_start
                cursor.window_to = newest_boundary
            last_checkpoint = day_start
            current_end = day_start
    except WindowFetchError as e:
        logger.error(
            "backfill_ml_orders_ops: window fetch failed, cursor NOT advanced past the last completed day: %s", e
        )
        failure = e
        result.error = str(e)
    except Exception as e:  # noqa: BLE001
        # Same structural guarantee as the sweep (obs #1852 lesson 1):
        # whatever happens above, the lock release below always runs.
        logger.exception("backfill_ml_orders_ops: backfill failed unexpectedly, releasing the run lock")
        failure = e
        result.error = f"{type(e).__name__}: {e}"
    finally:
        if failure is not None:
            release_lock_as_error(failure, cursor_name=CURSOR_NAME)
        else:
            # `already_up_to_date` did no work, so it must not refresh
            # `last_success_at`: a no-op keeping a staleness alert quiet is
            # the defect this chain has corrected three times already.
            complete = (
                not result.already_up_to_date and last_checkpoint is not None and last_checkpoint <= oldest_boundary
            )
            release_lock_as_idle(now, complete=complete, cursor_name=CURSOR_NAME)

    return result
