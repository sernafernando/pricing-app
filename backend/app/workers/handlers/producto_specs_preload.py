"""`producto_specs.preload`: pre-load the technical specs of every notebook and PC (abm-specs-productos S4). No cron.

Daily at 05:15 Argentina time, and right away on the first worker start after deploy (a job that never succeeded is
due once today's slot has passed), which is the initial backfill. Idempotent: an unchanged product writes nothing, and
a field an operator set by hand is never touched (`services.producto_specs.store.precargar`). New notebooks and PCs
get their specs on the next run; one product can be re-pre-loaded at once from the ABM (`POST
/api/producto-specs/{item_id}/precargar`).

Products go in batches of `BATCH_SIZE`, each in its own short transaction, so a manual edit waits at most one batch for
its row lock. When `ctx.deadline` passes, the run stops between batches with `success=False`: the job stays due and the
next pass pre-loads everything again (the batches already done write nothing the second time).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta

from app.core.database import get_background_db
from app.services.producto_specs import store
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


class ProductoSpecsPreloadHandler:
    """`JobHandler` for `producto_specs.preload`."""

    name = "producto_specs.preload"
    channels: tuple[str, ...] = ()
    interval: timedelta | None = None
    run_at_local: time | None = time(5, 15)
    # Measured in prod 2026-11-16: reading the ML attributes of every linked publication (~4.2k) takes ~5 s; the
    # whole run fits the default 30 s, this leaves room for a slow night without a partial run.
    deadline_seconds = 120

    def run(self, ctx: WorkerContext) -> JobResult:
        totals = {"productos": 0, "creados": 0, "actualizados": 0, "sin_cambios": 0, "lotes": 0}
        try:
            with get_background_db() as db:
                ids = [p.item_id for p in store.productos(db)]
            for start in range(0, len(ids), BATCH_SIZE):
                if datetime.now(UTC) >= ctx.deadline:
                    logger.info("producto_specs.preload: deadline reached, resuming next pass: %s", totals)
                    return JobResult(success=False, detail={**totals, "pendientes": len(ids) - start}, error="deadline")
                with get_background_db() as db:
                    counts = store.precargar(db, ids[start : start + BATCH_SIZE])
                    db.commit()
                for key, value in counts.items():
                    totals[key] += value
                totals["lotes"] += 1
        except Exception as exc:  # logged and retried on the next pass; finished batches stay committed
            logger.exception("producto_specs.preload failed")
            return JobResult(success=False, detail=totals, error=f"{type(exc).__name__}: {exc}")
        logger.info("producto_specs.preload: %s", totals)
        return JobResult(success=True, detail=totals)


preload = ProductoSpecsPreloadHandler()
