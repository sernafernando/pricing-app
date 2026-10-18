"""`sell.drain` (sell-in-sell-out T5): drains `sell_dirty` and recomputes the
sell-in allocation of every product the queued sale lines touch. No cron.

Each batch is ONE short `get_background_db()` transaction:

1. claim up to `BATCH_SIZE` lines (`FOR UPDATE SKIP LOCKED`, so concurrent
   drains split the queue instead of waiting on each other);
2. collect their products: the queued product plus the products the line's
   stored consumptions are filed under (a fuera / TN line moved to another
   product is queued under the NEW one only; its OLD product is found here);
3. recompute those products through the active `SellInCosting` strategy
   (per-product advisory lock, writes only the difference);
4. ack the lines whose products all succeeded; charge the rest
   (`attempts`/`last_error`). A charged line is not claimed again in this run,
   and is parked after `queue.MAX_ATTEMPTS` until a new change re-queues it.

An error outside the per-product savepoint (step 2, a recompute that does not
isolate it, step 4) rolls the whole batch back, so no line would ever be
charged and the next wake would claim the same batch again: one bad line would
stall the queue. Instead the drain retries that batch one line per transaction
(re-claimed with `SKIP LOCKED`), charging, in its own transaction, only the
line that still fails, and only while it is still the version that failed (a
re-queue that landed meanwhile is a fresh change). The others drain; the bad
one is parked in time.

Only a line's own fault is charged. A transient infrastructure error
(`is_transient`: a lost connection, a deadlock, a serialization failure, a
lock_not_available) charges nothing: the run stops, the lines stay queued as
they were, and the next wake retries them. A statement timeout (57014) is NOT
transient: a product whose recompute always times out would otherwise stop the
drain on every wake forever, so it is charged and parks like any bad line.

Sell out (T7) will join step 3. Wired like `tp_cost.fill`:
`channels=("sell_dirty",)` with no `interval`/`run_at_local`, so
`WorkerRuntime.drain_once` runs it on every LISTEN wake and on every safety
poll. On an empty queue that costs one query.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from app.core.database import get_background_db
from app.services.sell import queue
from app.services.sell_in.costing import RecomputeResult, get_costing
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

Claimed = Tuple[str, int, Optional[int]]

# deadlock, serialization failure, lock_not_available; plus class 08 (connection exceptions).
# Not 57014 (query_canceled / statement_timeout): it can be a product's own, permanent fault.
_TRANSIENT_SQLSTATES = frozenset({"40P01", "40001", "55P03"})


def is_transient(exc: BaseException) -> bool:
    """True for an infrastructure error that says nothing about the line being
    processed, so retrying later can succeed: an invalidated connection, a
    connection-level `OperationalError` without SQLSTATE, a class 08 SQLSTATE,
    or one of `_TRANSIENT_SQLSTATES`."""
    if not isinstance(exc, DBAPIError):
        return False
    if exc.connection_invalidated:
        return True
    pgcode = getattr(exc.orig, "pgcode", None)
    if pgcode is None:
        return isinstance(exc, OperationalError)
    return pgcode in _TRANSIENT_SQLSTATES or pgcode.startswith("08")


class SellDrainHandler:
    """`JobHandler` for `sell.drain`."""

    name = "sell.drain"
    channels: Tuple[str, ...] = (queue.CHANNEL,)
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        detail = {"lines": 0, "batches": 0, "products": 0, "inserted": 0, "deleted": 0, "failed": 0}
        failed_lines: Set[queue.Line] = set()
        stopped = False
        while not stopped and datetime.now(timezone.utc) < ctx.deadline:
            claimed: List[Claimed] = []
            try:
                with get_background_db() as db:
                    if db.get_bind().dialect.name != "postgresql":
                        # The queue, its triggers and SKIP LOCKED are Postgres-only.
                        break
                    claimed = queue.claim_batch(db, queue.BATCH_SIZE, excluded=failed_lines)
                    if not claimed:
                        break
                    result, failed = _recompute_and_settle(db, claimed)
            except Exception as exc:
                if is_transient(exc):
                    logger.warning("sell.drain: transient error, nothing charged; the next wake retries: %s", exc)
                    break
                if not claimed:
                    raise  # nothing was claimed: not a line's fault
                logger.exception("sell.drain: batch of %s line(s) failed; retrying it line by line", len(claimed))
                result, failed, stopped, processed = _line_by_line(claimed, ctx.deadline)
            else:
                processed = len(claimed)
            failed_lines.update(failed)
            detail["lines"] += processed
            detail["batches"] += 1
            detail["products"] += result.products
            detail["inserted"] += result.inserted
            detail["deleted"] += result.deleted
            detail["failed"] += len(failed)
            if failed:
                logger.warning("sell.drain: %s line(s) failed: %s", len(failed), failed)
            if len(claimed) < queue.BATCH_SIZE:
                break
        if detail["failed"]:
            logger.warning("sell.drain: run charged %s failed line(s)", detail["failed"])
        return JobResult(success=True, detail=detail)


def _recompute_and_settle(db: Session, claimed: Sequence[Claimed]) -> Tuple[RecomputeResult, Dict[queue.Line, str]]:
    """Recomputes every product the claimed lines touch, acks the lines whose
    products all succeeded and charges the rest. Does not commit."""
    products = queue.products_of(db, claimed)
    result = get_costing().recompute(db, set().union(*products.values()))
    failed: Dict[queue.Line, str] = {
        line: "; ".join(f"item {item}: {result.failed[item]}" for item in sorted(items & result.failed.keys()))
        for line, items in products.items()
        if items & result.failed.keys()
    }
    parked = queue.settle(db, [line for line in products if line not in failed], failed)
    for line in parked:
        _log_parked(line, failed[line])
    return result, failed


def _log_parked(line: queue.Line, error: str) -> None:
    """An ERROR, so it reaches alerting: a parked line is no longer retried
    until its sale changes, and many of them at once mean a systemic bug."""
    canal, ref = line
    logger.error(
        "sell.drain: line %s/%s parked after %s attempts; retried only when its sale changes again: %s",
        canal,
        ref,
        queue.MAX_ATTEMPTS,
        error,
    )


def _line_by_line(
    claimed: Sequence[Claimed], deadline: datetime
) -> Tuple[RecomputeResult, Dict[queue.Line, str], bool, int]:
    """Retries a batch that failed as a whole, one line per transaction. A line
    that fails on its own is charged in a separate transaction (its own rolled
    back), only if it is still the version claimed. A line another drain took,
    or that was acked or parked meanwhile, is skipped. Lines left when the
    deadline passes, or after a transient error (even one raised while
    charging; third value True: stop the run), stay queued, untouched, for the
    next wake. The fourth value counts the lines actually processed."""
    total = RecomputeResult()
    processed = 0
    failed: Dict[queue.Line, str] = {}
    for canal, ref, _ in claimed:
        if datetime.now(timezone.utc) >= deadline:
            break
        line = (canal, ref)
        version: Optional[datetime] = None
        try:
            with get_background_db() as db:
                again = queue.claim_line(db, line)
                if again is None:
                    continue
                row, version = again
                result, line_failed = _recompute_and_settle(db, [row])
        except Exception as exc:
            if is_transient(exc):
                logger.warning("sell.drain: transient error on line %s, nothing charged; stopping: %s", line, exc)
                return total, failed, True, processed
            if version is None:
                raise  # failed before the line was claimed: not the line's fault
            logger.exception("sell.drain: line %s failed", line)
            line_failed = {line: f"{type(exc).__name__}: {exc}"}
            try:
                with get_background_db() as db:
                    attempts = queue.charge(db, line, line_failed[line], version)
                if attempts is None:
                    logger.info("sell.drain: line %s was re-queued meanwhile; not charged", line)
                elif attempts >= queue.MAX_ATTEMPTS:
                    _log_parked(line, line_failed[line])
            except Exception as charge_exc:
                if not is_transient(charge_exc):
                    raise
                logger.warning(
                    "sell.drain: transient error charging line %s, not charged; stopping: %s", line, charge_exc
                )
                return total, failed, True, processed
            result = RecomputeResult()
        processed += 1
        failed.update(line_failed)
        total.products += result.products
        total.inserted += result.inserted
        total.deleted += result.deleted
    return total, failed, False, processed


drain = SellDrainHandler()
