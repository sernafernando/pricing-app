"""`tienda_nube.sync` (abm-productos L12): keeps `tienda_nube_productos` (variants, prices, published, ERP link) and
`tienda_nube_producto_textos` (name and description) in step with the Tienda Nube catalog. No cron: it replaces the
crontab line `*/15 6-21 * * * ... scripts/sync_tienda_nube.py`, with the same cadence.

Schedule-only, every 15 minutes; outside 06:00-21:59 Argentina time a run does nothing. The fetch (paged HTTP, no
database session open) is bounded by `ctx.deadline`; then one short `get_background_db()` transaction applies the
whole pass (`tienda_nube_sync_shared.sincronizar_catalogo`), so readers never see half of it. A failed or empty fetch
writes nothing; a partial one updates what it brought, inactivates nothing and reports `success=False`, and the next
interval retries.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta

from app.core.database import get_background_db
from app.services.tienda_nube_catalogo import fetch_productos
from app.services.tienda_nube_sync_shared import sincronizar_catalogo
from app.workers.context import JobResult, WorkerContext
from app.workers.scheduling import ARGENTINA_TZ

logger = logging.getLogger(__name__)

# The old cron's hours, `6-21`: from 06:00 to the 21:45 run.
HORA_DESDE = 6
HORA_HASTA = 21
# Under this much time left before `ctx.deadline`, a fetch is not worth starting.
MIN_FETCH_SECONDS = 5


def _now() -> datetime:
    return datetime.now(ARGENTINA_TZ)


def en_horario(now: datetime) -> bool:
    return HORA_DESDE <= now.astimezone(ARGENTINA_TZ).hour <= HORA_HASTA


class TiendaNubeSyncHandler:
    """`JobHandler` for `tienda_nube.sync`."""

    name = "tienda_nube.sync"
    channels: tuple[str, ...] = ()
    interval: timedelta | None = timedelta(minutes=15)
    run_at_local: time | None = None
    # Prod 2026-11-16: ~2.2k TN rows, ~11 pages of 200. Each page is bounded by `REQUEST_TIMEOUT_SECONDS` (20 s), so
    # even a slow TN fits; a run cut by the deadline is partial and logged with the pages it got.
    deadline_seconds = 240

    def run(self, ctx: WorkerContext) -> JobResult:
        if not en_horario(_now()):
            return JobResult(success=True, detail={"skipped": "fuera de horario"})
        if (ctx.deadline - datetime.now(UTC)).total_seconds() < MIN_FETCH_SECONDS:
            return JobResult(success=True, detail={"skipped": "deadline"})
        try:
            products, completo = fetch_productos(deadline=ctx.deadline)
        except Exception as exc:  # TN is outside our control: log, write nothing, retry next interval
            logger.warning("tienda_nube.sync: fetch failed, nothing written: %s", exc)
            return JobResult(success=False, error=f"{type(exc).__name__}: {exc}")
        if not products:
            return JobResult(success=False, error="Tienda Nube no devolvió productos; no se modificó nada")

        with get_background_db() as db:
            detail = sincronizar_catalogo(db, products, fetch_complete=completo)
            db.commit()
        if not completo:
            logger.warning("tienda_nube.sync: partial fetch, nothing inactivated: %s", detail)
            return JobResult(success=False, detail=detail, error="fetch parcial: no se desactivó ningún producto")
        logger.info("tienda_nube.sync: %s", detail)
        return JobResult(success=True, detail=detail)


sync = TiendaNubeSyncHandler()
