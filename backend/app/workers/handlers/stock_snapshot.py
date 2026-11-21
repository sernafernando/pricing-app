"""`stock.snapshot`: the daily stock photo of every product (auditoria-stock-rotacion L1). No cron.

Daily at 06:00 Argentina time in the drain pass of the existing ML worker (`pricing-worker-ml`: it reads the ML
store's Full), and right away on the first worker start after deploy
(a job that never succeeded is due once today's slot has passed), which starts the history the same day. One short
transaction: today's photo replaces any earlier take of today, and the photos older than 400 days are pruned on the
same run (`services.ml_publications.view.stock_snapshot`). A failure commits nothing and the job stays due.

Costo SI (sell-in-costo-si T2) rides on the same run, after the photo committed, so it can never cost the Auditoría
its photo, and reads its Full from that photo (`costo_si.full_ml`): first the day's available-stock photo of every
product with a costo SI (`costo_si.foto`), then every product, sell in or not (L21), queued for `sell.drain`
(`encolar_vigentes`), which brings the purchase invoices the GBP sync loaded into the average. It calls no Mercado
Libre endpoint. A failure there is logged and reported in the detail; the job still succeeds.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone

from app.core.database import get_background_db
from app.services.ml_daily_metrics import board
from app.services.costo_si import foto as costo_si_foto
from app.services.costo_si import queue as costo_si_queue
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
    deadline_seconds = 600

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
        detail.update(_costo_si(ctx, day))
        logger.info("stock.snapshot: %s", detail)
        return JobResult(success=True, detail=detail)


def _costo_si(ctx: WorkerContext, day: date) -> dict:
    """Costo SI's photo and daily re-queue (module docstring). Never raises."""
    try:
        with get_background_db() as db:
            fotografiados = costo_si_foto.tomar(
                db, day, datetime.now(timezone.utc), ctx.deadline - timedelta(seconds=10)
            )
            encolados = costo_si_queue.encolar_vigentes(db)
            db.commit()
    except Exception as exc:  # the Auditoría photo already committed; the next day retries
        logger.exception("stock.snapshot: costo SI part failed")
        return {"costo_si_error": f"{type(exc).__name__}: {exc}"}
    return {
        "costo_si_foto": fotografiados,
        "costo_si_encolados": encolados,
    }


snapshot = StockSnapshotHandler()
