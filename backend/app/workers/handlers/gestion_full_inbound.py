"""`gestion_full.inbound`: weekend drip that refreshes Full inbound Target snapshots.

Saturday–Sunday only (America/Argentina/Buenos_Aires). Interval ticks drip one
inventory_id per run with a short lookback (60 days) so ML operations quota is
not burned on weekdays. Weekday ticks return success=True skip (must not leave
the job due). Shares `refresh.pacer` with other ML publications handlers.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Callable, Optional, Tuple

from app.core import database
from app.services.gestion_full.inbound import (
    MAX_RANGE_DAYS,
    claim_inventory_ids_for_inbound_refresh,
    refresh_last_inbound,
)
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.ml_publications import refresh
from app.workers.scheduling import ARGENTINA_TZ

logger = logging.getLogger(__name__)

HANDLER_NAME = "gestion_full.inbound"
WEEKEND_WEEKDAYS = frozenset({5, 6})  # Saturday, Sunday
BATCH_PER_TICK = 1
FRESH_WITHIN_DAYS = 6
LOOKBACK_DAYS = MAX_RANGE_DAYS  # one ML window; enough for ~1–2 Fulls/week


class GestionFullInboundHandler:
    name = HANDLER_NAME
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(minutes=2)
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
        local = self._now().astimezone(ARGENTINA_TZ)
        if local.weekday() not in WEEKEND_WEEKDAYS:
            return JobResult(success=True, detail={"skipped": "weekday", "weekday": local.weekday()})

        if self._client is None:
            self._client = self._client_factory(self.pacer)

        with self._session_factory() as db:
            inventory_ids = claim_inventory_ids_for_inbound_refresh(
                db,
                limit=BATCH_PER_TICK,
                fresh_within_days=FRESH_WITHIN_DAYS,
                now=self._now(),
            )

        if not inventory_ids:
            return JobResult(success=True, detail={"refreshed": 0, "complete": True})

        refreshed = 0
        errors: list[str] = []
        for inventory_id in inventory_ids:
            if ctx.stop_requested():
                break
            try:
                with self._session_factory() as db:
                    refresh_last_inbound(
                        db,
                        inventory_id,
                        client=self._client,
                        lookback_days=LOOKBACK_DAYS,
                    )
                refreshed += 1
            except Exception as exc:  # noqa: BLE001 -- keep drip alive; retry next tick
                logger.exception("gestion_full.inbound failed for %s", inventory_id)
                errors.append(f"{inventory_id}:{type(exc).__name__}")

        return JobResult(
            success=True,
            detail={
                "refreshed": refreshed,
                "attempted": inventory_ids,
                "errors": errors,
                "complete": refreshed == 0 and not errors,
            },
        )


inbound = GestionFullInboundHandler(pacer=refresh.pacer)
