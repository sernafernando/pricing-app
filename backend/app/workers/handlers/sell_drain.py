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

Sell out (T7) will join step 3. Wired like `tp_cost.fill`:
`channels=("sell_dirty",)` with no `interval`/`run_at_local`, so
`WorkerRuntime.drain_once` runs it on every LISTEN wake and on every safety
poll. On an empty queue that costs one query.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Dict, Optional, Set, Tuple

from app.core.database import get_background_db
from app.services.sell import queue
from app.services.sell_in.costing import get_costing
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)


class SellDrainHandler:
    """`JobHandler` for `sell.drain`."""

    name = "sell.drain"
    channels: Tuple[str, ...] = (queue.CHANNEL,)
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        detail = {"lines": 0, "batches": 0, "products": 0, "inserted": 0, "deleted": 0, "failed": 0}
        failed_lines: Set[queue.Line] = set()
        while datetime.now(timezone.utc) < ctx.deadline:
            with get_background_db() as db:
                if db.get_bind().dialect.name != "postgresql":
                    # The queue, its triggers and SKIP LOCKED are Postgres-only.
                    break
                claimed = queue.claim_batch(db, queue.BATCH_SIZE, excluded=failed_lines)
                if not claimed:
                    break
                products = queue.products_of(db, claimed)
                result = get_costing().recompute(db, set().union(*products.values()))
                failed: Dict[queue.Line, str] = {
                    line: "; ".join(
                        f"item {item}: {result.failed[item]}" for item in sorted(items & result.failed.keys())
                    )
                    for line, items in products.items()
                    if items & result.failed.keys()
                }
                queue.settle(db, [line for line in products if line not in failed], failed)
            failed_lines.update(failed)
            detail["lines"] += len(claimed)
            detail["batches"] += 1
            detail["products"] += result.products
            detail["inserted"] += result.inserted
            detail["deleted"] += result.deleted
            detail["failed"] += len(failed)
            if failed:
                logger.warning("sell.drain: %s line(s) failed: %s", len(failed), result.failed)
            if len(claimed) < queue.BATCH_SIZE:
                break
        return JobResult(success=True, detail=detail)


drain = SellDrainHandler()
