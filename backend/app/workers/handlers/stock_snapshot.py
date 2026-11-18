"""`stock.snapshot`: the daily stock photo of every product (auditoria-stock-rotacion L1). No cron.

Daily at 06:00 Argentina time in the drain pass of the existing ML worker (`pricing-worker-ml`: it reads the ML
store's Full), and right away on the first worker start after deploy
(a job that never succeeded is due once today's slot has passed), which starts the history the same day. One short
transaction: today's photo replaces any earlier take of today, and the photos older than 400 days are pruned on the
same run (`services.ml_publications.view.stock_snapshot`). A failure commits nothing and the job stays due.
"""

from __future__ import annotations

import logging
from datetime import time, timedelta

from app.core.database import get_background_db
from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import stock_snapshot
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)


class StockSnapshotHandler:
    """`JobHandler` for `stock.snapshot`."""

    name = "stock.snapshot"
    channels: tuple[str, ...] = ()
    interval: timedelta | None = None
    run_at_local: time | None = time(6, 0)
    # Two reads (the ERP stock and the Full units of every linked publication, the Auditoría's own query) and one
    # bulk insert of the products with stock: seconds; this leaves room for a slow morning.
    deadline_seconds = 120

    def run(self, ctx: WorkerContext) -> JobResult:
        day = board.today_business()
        try:
            with get_background_db() as db:
                productos = stock_snapshot.take(db, day)
                borrados = stock_snapshot.prune(db, day)
                db.commit()
        except Exception as exc:  # logged and retried on the next pass; nothing was committed
            logger.exception("stock.snapshot failed")
            return JobResult(success=False, detail={"fecha": day.isoformat()}, error=f"{type(exc).__name__}: {exc}")
        detail = {"fecha": day.isoformat(), "productos": productos, "borrados": borrados}
        logger.info("stock.snapshot: %s", detail)
        return JobResult(success=True, detail=detail)


snapshot = StockSnapshotHandler()
