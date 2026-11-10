"""`compras.factura_cargada_alerts`: fire pending ERP-check alerts after the 5-minute delay.

No cron. Schedule-only (`channels=()`), every minute on the main worker
(`pricing-worker.service` / `REGISTRY`). Replaces
`python -m app.scripts.dispatch_factura_cargada_alerts` as the SoT schedule;
that script stays as a thin manual wrapper.

Calls `compras_alertas_service.disparar_alertas_factura_pendientes` in one short
`get_background_db()` block. Idempotent: already-fired rows are skipped.
"""

from __future__ import annotations

import logging
from datetime import time, timedelta

from app.core.database import get_background_db
from app.services import compras_alertas_service
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

HANDLER_NAME = "compras.factura_cargada_alerts"


class ComprasFacturaCargadaAlertsHandler:
    """`JobHandler` for pending `compras.factura_cargada` fan-out."""

    name = HANDLER_NAME
    channels: tuple[str, ...] = ()
    interval: timedelta | None = timedelta(minutes=1)
    run_at_local: time | None = None

    def run(self, ctx: WorkerContext) -> JobResult:
        try:
            with get_background_db() as db:
                fired = compras_alertas_service.disparar_alertas_factura_pendientes(db)
        except Exception as exc:
            logger.warning("%s: sweep failed: %s", HANDLER_NAME, exc)
            return JobResult(success=False, error=f"{type(exc).__name__}: {exc}")
        if fired:
            logger.info("%s: fired=%s", HANDLER_NAME, fired)
        return JobResult(success=True, detail={"fired": fired})


factura_cargada_alerts = ComprasFacturaCargadaAlertsHandler()
