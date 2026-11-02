"""`gestion_full.reconcile`: poll open envíos every 3h for INBOUND_RECEPTION ops."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Callable, Optional, Tuple

from app.core import database
from app.models.gestion_full_envio import GestionFullEnvio
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

        # Copy inbound_ids while the listing session is open — ORM rows detach on close.
        with self._session_factory() as db:
            open_inbound_ids = [e.inbound_id for e in list_open_envios(db)[:BATCH_PER_TICK]]

        if not open_inbound_ids:
            return JobResult(success=True, detail={"reconciled": 0, "complete": True})

        results = []
        for inbound_id in open_inbound_ids:
            if ctx.stop_requested():
                break
            try:
                with self._session_factory() as db:
                    row = db.get(GestionFullEnvio, inbound_id)
                    if row is None:
                        continue
                    results.append(reconcile_envio(db, row, client=self._client, now=self._now()))
            except Exception:  # noqa: BLE001 -- keep poller alive
                logger.exception("gestion_full.reconcile failed for %s", inbound_id)
                results.append({"inbound_id": inbound_id, "error": True})

        # Exceptions set error=True; all-429 (ml_fail>0, ml_ok==0) must also fail the job
        # so the worker does not report success when every envío hit ML errors.
        def _failed(r: object) -> bool:
            if not isinstance(r, dict):
                return True
            if r.get("error"):
                return True
            if r.get("skipped"):
                return False
            inventories = r.get("inventories") or []
            return bool(inventories) and int(r.get("ml_fail") or 0) > 0 and int(r.get("ml_ok") or 0) == 0

        all_failed = bool(results) and all(_failed(r) for r in results)
        return JobResult(
            success=not all_failed,
            detail={"reconciled": len(results), "results": results},
        )


reconcile = GestionFullReconcileHandler(pacer=refresh.pacer)
