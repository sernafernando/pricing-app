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
from app.services.ml_orders_ingestion.mapper import MappingError, map_order
from app.services.ml_orders_ingestion.sweep_service import (
    CURSOR_NAME as SWEEP_CURSOR_NAME,
    SweepResult,
    WindowFetchError,
    ensure_cursor_row,
    iter_window_events,
    load_cursor,
    process_batch,
    release_lock_as_error,
    release_lock_as_idle,
    try_acquire_run_lock,
    tz_aware,
)

logger = logging.getLogger(__name__)

CURSOR_NAME = "backfill"

# Never reused by anything else: guards against a future refactor
# accidentally pointing the backfill at the sweep's own row.
assert CURSOR_NAME != SWEEP_CURSOR_NAME

DAY = timedelta(days=1)

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
    budget_exhausted: bool = False
    error: Optional[str] = None


def _dry_run_count_window(seller_id: int, day_from: datetime, day_to: datetime) -> int:
    """The `--dry-run` equivalent of `process_batch`: enumerates the
    window (so `search_orders` really is called and the window bounds are
    really computed, per the RED test's own promise) but never opens a DB
    session and never calls `upsert_order` -- zero writes, by construction
    rather than by a flag threaded through the write path."""
    seen = 0
    for event in iter_window_events(seller_id, day_from, day_to):
        kind = event[0]
        if kind == "page":
            for raw_order in event[1]:
                seen += 1
                mapped = map_order(raw_order)
                if isinstance(mapped, MappingError):
                    continue
        elif kind == "budget_exhausted":
            logger.warning(
                "backfill(dry-run): fetch budget spent before [%s, %s) finished enumerating",
                day_from.isoformat(),
                day_to.isoformat(),
            )
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
    return seen


def _process_day(seller_id: int, day_from: datetime, day_to: datetime, result: BackfillResult) -> bool:
    """Processes one calendar-day window for real, reusing the sweep's
    exact streaming walk + bounded-batch upsert. Raises `WindowFetchError`
    on an unresolved fetch failure (fail-closed per day, mirroring the
    sweep's fail-closed-per-window contract) -- the caller must not
    checkpoint past a day that raised.

    Returns True only if the day was FULLY enumerated. False means the
    fetch budget ran out partway through this single day: the caller must
    NOT checkpoint `window_from` past `day_from` in that case, so the next
    pass resumes and finishes this exact day instead of treating a
    partial day as done."""
    sweep_shaped_result = SweepResult(ran=True)
    pending: list = []
    day_completed = True

    def _flush() -> None:
        nonlocal pending
        if pending:
            process_batch(pending, day_from, sweep_shaped_result)
            pending = []

    for event in iter_window_events(seller_id, day_from, day_to):
        kind = event[0]
        if kind == "page":
            pending.extend(event[1])
            while len(pending) >= 200:
                process_batch(pending[:200], day_from, sweep_shaped_result)
                pending = pending[200:]
        elif kind == "unenumerable":
            _, leaf_from, leaf_to = event
            sweep_shaped_result.windows_unenumerable += 1
            logger.warning(
                "backfill: [%s, %s) is not enumerable even at the minimum bisect span -- recorded, skipped",
                leaf_from.isoformat(),
                leaf_to.isoformat(),
            )
        elif kind == "budget_exhausted":
            day_completed = False
            logger.warning(
                "backfill: fetch budget spent before day [%s, %s) finished; will resume this exact day next run",
                day_from.isoformat(),
                day_to.isoformat(),
            )
    _flush()

    result.orders_seen += sweep_shaped_result.orders_seen
    result.orders_upserted += sweep_shaped_result.orders_upserted
    result.orders_skipped_stale += sweep_shaped_result.orders_skipped_stale
    result.orders_mapping_error += sweep_shaped_result.orders_mapping_error
    result.orders_out_of_window += sweep_shaped_result.orders_out_of_window
    return day_completed


def run_backfill(
    days_from: int = 0,
    days_to: Optional[int] = None,
    seller_id: Optional[int] = None,
    dry_run: bool = False,
) -> BackfillResult:
    """Entry point for `app/scripts/backfill_ml_orders_ops.py`.

    Flag-gated exactly like the sweep: a complete no-op (zero HTTP calls,
    zero DB reads/writes) while `ML_ORDERS_OPS_ENABLED` is False.

    Walks day-sized windows BACKWARDS from `now - days_from` down to
    `now - days_to`, checkpointing `ml_ops_sync_cursor(name='backfill')`
    after each day so a killed run resumes at the last fully-completed
    day instead of restarting (see module docstring).
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

    result = BackfillResult(ran=True, dry_run=dry_run)

    if dry_run:
        # Dry runs never touch the lock or the cursor: no progress is
        # persisted, so a subsequent real run is never short-circuited by
        # a dry run's own "completed" checkpoint (see module docstring).
        current_end = newest_boundary
        while current_end > oldest_boundary:
            day_start = max(current_end - DAY, oldest_boundary)
            _dry_run_count_window(int(resolved_seller_id), day_start, current_end)
            result.days_completed += 1
            current_end = day_start
        return result

    with get_background_db() as db:
        acquired = try_acquire_run_lock(db, now, cursor_name=CURSOR_NAME)
        if not acquired:
            logger.info("backfill_ml_orders_ops: another backfill run is already in flight, skipping this pass")
            return BackfillResult(ran=False, dry_run=dry_run, error="already running")
        ensure_cursor_row(db, cursor_name=CURSOR_NAME)
        cursor = load_cursor(db, cursor_name=CURSOR_NAME)
        resume_from = tz_aware(cursor.window_from) if cursor is not None else None

    current_end = resume_from if resume_from is not None else newest_boundary
    if current_end > newest_boundary:
        current_end = newest_boundary

    failure: Optional[BaseException] = None
    last_checkpoint: Optional[datetime] = resume_from

    try:
        while current_end > oldest_boundary:
            day_start = max(current_end - DAY, oldest_boundary)
            day_completed = _process_day(int(resolved_seller_id), day_start, current_end, result)

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
            complete = last_checkpoint is not None and last_checkpoint <= oldest_boundary
            release_lock_as_idle(now, complete=complete, cursor_name=CURSOR_NAME)

    return result
