"""`sell.drain` (sell-in-sell-out T4): drains `sell_dirty`. No cron.

INERT ON PURPOSE. It claims queued sale lines and acks (deletes) them WITHOUT
computing any sell-in or sell-out allocation: the FIFO allocator lands in T5
and the sell-out allocator in T7. It exists now so the queue the triggers and
`store_sale_lines` feed never grows unbounded. Whatever it acks before T5 is
covered by T5's initial backfill, not by this queue.

Wired like `tp_cost.fill`: `channels=("sell_dirty",)` with no
`interval`/`run_at_local`, so `WorkerRuntime.drain_once` runs it on every
LISTEN wake and on every safety poll. On an empty queue that costs one query.
Each batch is its own short `get_background_db()` transaction.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Optional, Tuple

from app.core.database import get_background_db
from app.services.sell import queue
from app.workers.context import JobResult, WorkerContext


class SellDrainHandler:
    """`JobHandler` for `sell.drain` (inert until T5)."""

    name = "sell.drain"
    channels: Tuple[str, ...] = (queue.CHANNEL,)
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        detail = {"acked": 0, "batches": 0}
        while datetime.now(timezone.utc) < ctx.deadline:
            with get_background_db() as db:
                if db.get_bind().dialect.name != "postgresql":
                    # The queue, its triggers and SKIP LOCKED are Postgres-only.
                    break
                acked = queue.ack_batch(db, queue.BATCH_SIZE)
            if not acked:
                break
            detail["acked"] += len(acked)
            detail["batches"] += 1
            if len(acked) < queue.BATCH_SIZE:
                break
        return JobResult(success=True, detail=detail)


drain = SellDrainHandler()
