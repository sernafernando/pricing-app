"""`sell_out.drain` (sell-in-sell-out T7 S3): drains `sell_out_dirty` and
rebuilds the queued campaigns' `sell_out_consumos` (`asignacion.recalcular`,
which also rebuilds every active campaign sharing products with them). No cron:
the queue's writers `pg_notify('sell_out_dirty')` (`app.services.sell_out.queue`).

Each batch is ONE short `get_background_db()` transaction: claim up to
`queue.BATCH_SIZE` campaigns (`FOR UPDATE SKIP LOCKED`, so concurrent drains
split the queue), rebuild them together, ack them.

A rebuild fails as a whole (a USD campaign without a rate, a product without
VAT: `SellOutAsignacionError`), so a failed batch is retried one campaign per
transaction and only the campaign that still fails is charged
(`attempts`/`last_error`), in its own transaction, while it is still the
version claimed (a re-queue that landed meanwhile is a fresh change). A charged
campaign is not claimed again in this run and parks after `queue.MAX_ATTEMPTS`
until something queues it again. Campaigns sharing products are rebuilt
together, so one of them failing charges the others it drags in too: their
allocations depend on it.

A transient infrastructure error (`sell_drain.is_transient`), even while
charging, charges nothing: the run stops, keeping its counters, and the next
wake retries. Errors are kept to `ERROR_MAX` chars, stored and logged.

Wired like `sell_in.bono`: `channels=("sell_out_dirty",)` with no
`interval`/`run_at_local`, so `WorkerRuntime.drain_once` runs it on every LISTEN
wake and every safety poll; an empty queue costs one query.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from app.core.database import get_background_db
from app.services.sell_out import asignacion, queue
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.sell_drain import is_transient

logger = logging.getLogger(__name__)

ERROR_MAX = 500  # chars of an error kept in `last_error` and in the log lines


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:ERROR_MAX]


def _log_parked(campana_id: int, error: str) -> None:
    logger.error(
        "sell_out.drain: campaign %s parked after %s attempts; retried only when it is queued again: %s",
        campana_id,
        queue.MAX_ATTEMPTS,
        error,
    )


class SellOutDrainHandler:
    """`JobHandler` for `sell_out.drain`."""

    name = "sell_out.drain"
    channels: Tuple[str, ...] = (queue.CHANNEL,)
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        detail = {"campanas": 0, "batches": 0, "inserted": 0, "deleted": 0, "pendientes_base": 0, "failed": 0}
        failed_ids: Set[int] = set()
        while datetime.now(timezone.utc) < ctx.deadline:
            claimed: List[int] = []
            try:
                with get_background_db() as db:
                    if db.get_bind().dialect.name != "postgresql":
                        break  # the queue and SKIP LOCKED are Postgres-only
                    claimed = queue.claim_batch(db, queue.BATCH_SIZE, excluded=failed_ids)
                    if not claimed:
                        break
                    results = [asignacion.recalcular(db, claimed)]
                    queue.ack(db, claimed)
                failed: Dict[int, str] = {}
                stopped = False
            except Exception as exc:
                if is_transient(exc):
                    logger.warning("sell_out.drain: transient error, nothing charged; the next wake retries: %s", exc)
                    break
                if not claimed:
                    raise  # nothing was claimed: not a campaign's fault
                logger.exception("sell_out.drain: batch of %s campaign(s) failed; retrying one by one", len(claimed))
                results, failed, stopped = _one_by_one(claimed, ctx.deadline)
            failed_ids.update(failed)
            detail["campanas"] += len(claimed)
            detail["batches"] += 1
            detail["failed"] += len(failed)
            for result in results:
                detail["inserted"] += result.inserted
                detail["deleted"] += result.deleted
                detail["pendientes_base"] += sum(result.pendientes_base.values())
            if failed:
                logger.warning("sell_out.drain: %s campaign(s) failed: %s", len(failed), sorted(failed))
            if stopped or len(claimed) < queue.BATCH_SIZE:
                break
        return JobResult(success=True, detail=detail)


def _one_by_one(
    claimed: Sequence[int], deadline: datetime
) -> Tuple[List[asignacion.RecomputeResult], Dict[int, str], bool]:
    """Retries a batch that failed as a whole, one campaign per transaction; the third value is True
    when a transient error stopped it (the remaining campaigns stay queued, untouched)."""
    results: List[asignacion.RecomputeResult] = []
    failed: Dict[int, str] = {}
    for campana_id in claimed:
        if datetime.now(timezone.utc) >= deadline:
            break
        version: Optional[datetime] = None
        try:
            with get_background_db() as db:
                version = queue.claim_one(db, campana_id)
                if version is None:
                    continue  # acked, parked or taken by another drain meanwhile
                results.append(asignacion.recalcular(db, [campana_id]))
                queue.ack(db, [campana_id])
        except Exception as exc:
            if is_transient(exc):
                logger.warning("sell_out.drain: transient error on campaign %s, stopping: %s", campana_id, exc)
                return results, failed, True
            if version is None:
                raise  # failed before the campaign was claimed: not its fault
            logger.exception("sell_out.drain: campaign %s failed", campana_id)
            error = _error(exc)
            try:
                with get_background_db() as db:
                    attempts = queue.charge(db, campana_id, error, version)
            except Exception as charge_exc:
                if is_transient(charge_exc):
                    logger.warning(
                        "sell_out.drain: transient error charging campaign %s, stopping: %s", campana_id, charge_exc
                    )
                    return results, failed, True
                raise
            if attempts is not None:
                failed[campana_id] = error
                if attempts >= queue.MAX_ATTEMPTS:
                    _log_parked(campana_id, error)  # committed
    return results, failed, False


drain = SellOutDrainHandler()
