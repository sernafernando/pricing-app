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
until nothing due is left or `ctx.deadline` is reached.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Optional, Tuple

from app.core.database import get_background_db
from app.services.ml_orders_ingestion import ingestion_service
from app.workers.context import JobResult, WorkerContext


class QuarantineRetryHandler:
    """`JobHandler` for `ml_orders.quarantine_retry`."""

    name = "ml_orders.quarantine_retry"
    channels: Tuple[str, ...] = (ingestion_service.QUARANTINE_CHANNEL,)
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        detail = {"attempted": 0, "recovered": 0, "still_failed": 0, "passes": 0}
        limit = ingestion_service.MAX_QUARANTINE_RETRIES_PER_PASS
        while datetime.now(timezone.utc) < ctx.deadline:
            # One short transaction per pass: commits the recovered orders and
            # releases the connection before the next pass (DB pool rule).
            with get_background_db() as db:
                result = ingestion_service.retry_quarantined_orders(db, limit=limit)
            detail["passes"] += 1
            detail["attempted"] += result.attempted
            detail["recovered"] += result.recovered
            detail["still_failed"] += result.still_failed
            # A failed retry pushes its row's backoff forward, so a full pass
            # never selects the same rows again: a short pass means nothing
            # due is left.
            if result.attempted < limit:
                break
        return JobResult(success=True, detail=detail)


quarantine_retry = QuarantineRetryHandler()
