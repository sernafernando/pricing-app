"""`producto_specs.preload`: pre-load the technical specs of every notebook and PC (abm-specs-productos S4). No cron.

Daily at 05:15 Argentina time, and right away on the first worker start after deploy (a job that never succeeded is
due once today's slot has passed), which is the initial backfill. Idempotent: an unchanged product writes nothing, and
a field an operator set by hand is never touched (`services.producto_specs.store.precargar`). New notebooks and PCs
get their specs on the next run; one product can be re-pre-loaded at once from the ABM (`POST
/api/producto-specs/{item_id}/precargar`).
"""

from __future__ import annotations

import logging
from datetime import time, timedelta

from app.core.database import get_background_db
from app.services.producto_specs import store
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)


class ProductoSpecsPreloadHandler:
    """`JobHandler` for `producto_specs.preload`."""

    name = "producto_specs.preload"
    channels: tuple[str, ...] = ()
    interval: timedelta | None = None
    run_at_local: time | None = time(5, 15)

    def run(self, ctx: WorkerContext) -> JobResult:
        try:
            with get_background_db() as db:
                counts = store.precargar(db)
                db.commit()
        except Exception as exc:  # logged and retried on the next pass; nothing half-written (one transaction)
            logger.exception("producto_specs.preload failed")
            return JobResult(success=False, error=f"{type(exc).__name__}: {exc}")
        logger.info("producto_specs.preload: %s", counts)
        return JobResult(success=True, detail=counts)


preload = ProductoSpecsPreloadHandler()
