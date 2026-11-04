"""`ml_publications.catalog_competition_refresh`: drain catalog-competition refresh queue.

When `hay_mejores_ofertas` is newly set, the promotions store enqueues the MLA into
`catalog_competition_refresh_pending`. This handler persists a fresh
`ml_catalog_competition` snapshot via `refrescar_competencia_catalogo` (same path as the
panel's refresh button). No UI; no cron — runs in the ML worker.
"""

from __future__ import annotations

import logging
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from app.core import database
from app.services import catalog_competition_refresh_queue as queue
from app.services.ml_catalog_competition_service import refrescar_competencia_catalogo
from app.utils.async_bridge import resolve_maybe_async
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

HANDLER_NAME = "ml_publications.catalog_competition_refresh"
MAX_ROWS_PER_RUN = 10


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CatalogCompetitionRefreshHandler:
    name = HANDLER_NAME
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(seconds=30)
    run_at_local: Optional[dtime] = None

    def __init__(self, *, session_factory: Optional[Callable[[], Any]] = None) -> None:
        self._session_factory = session_factory or (lambda: database.get_background_db())

    def run(self, ctx: WorkerContext) -> JobResult:
        detail: Dict[str, Any] = {"refreshed": 0, "failed": 0, "quarantined": 0}
        stopped: Optional[str] = None
        for _ in range(MAX_ROWS_PER_RUN):
            if _utcnow() >= ctx.deadline:
                stopped = "deadline"
                break
            with self._session_factory() as db:
                claim = queue.claim_one(db, _utcnow())
            if claim is None:
                break
            ok = self._refresh(claim.mla)
            with self._session_factory() as db:
                if ok:
                    queue.drop(db, claim)
                    detail["refreshed"] += 1
                else:
                    outcome = queue.fail(db, claim, _utcnow())
                    if outcome == queue.OUTCOME_QUARANTINED:
                        detail["quarantined"] += 1
                    else:
                        detail["failed"] += 1
        if stopped:
            detail["stopped"] = stopped
        return JobResult(success=True, detail=detail)

    def _refresh(self, mla: str) -> bool:
        """Persist one snapshot. Never raises: one MLA must not stop the pass."""
        try:
            with self._session_factory() as db:
                resolve_maybe_async(refrescar_competencia_catalogo(db, [mla]))
            return True
        except Exception:  # noqa: BLE001
            logger.warning("catalog_competition_refresh: refresh failed for %s", mla, exc_info=True)
            return False


catalog_competition_refresh = CatalogCompetitionRefreshHandler()
