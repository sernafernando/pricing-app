"""`gestion_full.reconcile`: poll open envíos every 3h for INBOUND_RECEPTION ops."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Callable, Optional, Tuple

from app.core import database
from app.services.gestion_full.reconcile import list_open_envios, reconcile_envio
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.ml_publications import refresh

logger = logging.getLogger(__name__)

HANDLER_NAME = "gestion_full.reconcile"
BATCH_PER_TICK = 5


class GestionFullReconcileHandler:
    name = HANDLER_NAME
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(hours=3)
    run_at_local = None

    def __init__(
        self,
        *,
        client_factory: Optional[Callable[[Pacer], MlHttpClient]] = None,
        pacer: Optional[Pacer] = None,
        session_factory: Optional[Callable] = None,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.pacer = pacer or Pacer()
        self._client_factory = client_factory or (lambda pacer: MlHttpClient(pacer=pacer))
        self._client: Optional[MlHttpClient] = None
        self._session_factory = session_factory or (lambda: database.get_background_db())
        self._now = now or (lambda: datetime.now(UTC))

    def run(self, ctx: WorkerContext) -> JobResult:
        if self._client is None:
            self._client = self._client_factory(self.pacer)

        with self._session_factory() as db:
            open_envios = list_open_envios(db)[:BATCH_PER_TICK]

        if not open_envios:
            return JobResult(success=True, detail={"reconciled": 0, "complete": True})

        results = []
        for envio in open_envios:
            if ctx.stop_requested():
                break
            try:
                with self._session_factory() as db:
                    # re-load in this session
                    from app.models.gestion_full_envio import GestionFullEnvio

                    row = db.get(GestionFullEnvio, envio.inbound_id)
                    if row is None:
                        continue
                    results.append(reconcile_envio(db, row, client=self._client, now=self._now()))
            except Exception:  # noqa: BLE001 -- keep poller alive
                logger.exception("gestion_full.reconcile failed for %s", envio.inbound_id)
                results.append({"inbound_id": envio.inbound_id, "error": True})

        return JobResult(
            success=True,
            detail={"reconciled": len(results), "results": results},
        )


reconcile = GestionFullReconcileHandler(pacer=refresh.pacer)
