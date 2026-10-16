"""`tp_cost.fill` (metricas-ml-tplink-mode P2): fills the TP-Link cost of
sales flagged without one when a list-8 price shows up. No cron.

Wired like `order_metrics.drain`: `channels=("tp_cost_fill",)` with no
`interval`/`run_at_local`, so `WorkerRuntime.drain_once` runs it on every
LISTEN wake (the triggers in `services/ml_orders_ingestion/tp_cost_fill.py`
notify that channel) AND on every safety poll. On an empty queue that costs
one query. Otherwise it drains `tp_cost_fill_queue` in batches of
`BATCH_ITEMS`, each in its own short `get_background_db()` transaction, until
the queue is empty or `ctx.deadline` is reached.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional, Tuple

from app.core.database import get_background_db
from app.services.ml_orders_ingestion import tp_cost_fill as service
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)


class TpCostFillHandler:
    """`JobHandler` for `tp_cost.fill`."""

    name = "tp_cost.fill"
    channels: Tuple[str, ...] = (service.CHANNEL,)
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        detail = {"items": 0, "batches": 0, "written": 0, "failed": 0}
        # Failed items are charged in the queue and not claimed again in this
        # run: the next wake or safety poll retries them, until they park.
        failed: set[int] = set()
        while datetime.now(timezone.utc) < ctx.deadline:
            # `get_background_db` commits only when the block exits cleanly and
            # rolls back on an exception, so a batch-level error leaves the
            # queue exactly as it was.
            with get_background_db() as db:
                if db.get_bind().dialect.name != "postgresql":
                    # The queue, its triggers and SKIP LOCKED are Postgres-only.
                    break
                batch = service.fill_batch(db, service.BATCH_ITEMS, excluded=failed)
            if batch.items == 0:
                break
            failed.update(batch.failed)
            detail["items"] += batch.items
            detail["batches"] += 1
            detail["written"] += batch.result.written
            detail["failed"] += len(batch.failed)
            if batch.result.skipped:
                logger.info(
                    "tp_cost.fill: %s item(s), written=%s skipped=%s",
                    batch.items,
                    batch.result.written,
                    dict(batch.result.skipped),
                )
        return JobResult(success=True, detail=detail)


fill = TpCostFillHandler()
