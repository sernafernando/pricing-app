"""`ml_orders.quarantine_retry`: retries ML orders whose write failed
(`ml_orders_ops_cuarentena`) until they land. No cron.

Wired like `tp_cost.fill`: `channels=(QUARANTINE_CHANNEL,)` with no
`interval`/`run_at_local`, so `WorkerRuntime.drain_once` runs it on every
LISTEN wake (`ingestion_service._quarantine_order` notifies the channel inside
the quarantining transaction) AND on every safety poll -- which is also what
retries a row once its backoff expires, with no notify. On an empty or
not-yet-due quarantine that costs one indexed query.

`retry_quarantined_orders` owns the policy (backoff, transient vs permanent,
attempt cap); this handler only runs it in short `get_background_db()` passes
until nothing due is left or `ctx.deadline` is reached. Before that, the rows
with no payload (orders ML never gave the activity receiver) are asked again
of ML (`activity_receiver_service.refetch_unresolved_orders`): an order ML
gives back is written, one ML has no longer is dropped.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional, Tuple

from app.core.database import get_background_db
from app.services.ml_orders_ingestion import activity_receiver_service, ingestion_service
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)


class QuarantineRetryHandler:
    """`JobHandler` for `ml_orders.quarantine_retry`."""

    name = "ml_orders.quarantine_retry"
    channels: Tuple[str, ...] = (ingestion_service.QUARANTINE_CHANNEL,)
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        # First the orders ML never gave back (no payload to replay): asked
        # again, and the ones that come back are written in that same pass.
        # Neither a failure there (the pool, the proxy) nor a slow proxy may
        # hold back the replay of the orders whose write failed: an exception
        # is logged, and the re-fetch gets at most half of the run's time.
        now = datetime.now(timezone.utc)
        refetch_deadline = now + max(ctx.deadline - now, timedelta(0)) / 2
        try:
            refetch = activity_receiver_service.refetch_unresolved_orders(deadline=refetch_deadline)
        except Exception:
            logger.exception("ml_orders.quarantine_retry: re-fetch of the payload-less orders failed")
            refetch = activity_receiver_service.RefetchResult()
        detail = {
            "refetched": refetch.attempted,
            "refetch_landed": refetch.landed,
            "dropped": refetch.dropped,
            "refetch_failed": refetch.failed,
            "attempted": 0,
            "recovered": 0,
            "still_failed": 0,
            "passes": 0,
        }
        limit = ingestion_service.MAX_QUARANTINE_RETRIES_PER_PASS
        seen: set[int] = set()
        while datetime.now(timezone.utc) < ctx.deadline:
            # One short transaction per pass: commits the recovered orders and
            # releases the connection before the next pass (DB pool rule).
            with get_background_db() as db:
                result = ingestion_service.retry_quarantined_orders(db, limit=limit)
            # This pass's orders were replayed, so they count even when it is
            # the last one.
            detail["passes"] += 1
            detail["attempted"] += result.attempted
            detail["recovered"] += result.recovered
            detail["still_failed"] += result.still_failed
            if result.order_ids and seen.issuperset(result.order_ids):
                # Only orders this run already replayed: they are still due
                # (their attempt could not be recorded), so another pass would
                # replay them until the deadline. The next wake retries them.
                break
            seen.update(result.order_ids)
            # A retried row's backoff moves forward, so a short pass means
            # nothing due is left.
            if result.attempted < limit:
                break
        return JobResult(success=True, detail=detail)


quarantine_retry = QuarantineRetryHandler()
