"""`ml_orders.discounts`: per-sale discounts (`GET /orders/{order_id}/discounts`) of the sales paid with a coupon.

Runs in its own thread of the existing ML worker (`own_thread`), no cron: its runs wait on the pacer gate, so
they must never delay the handlers of the shared pass. Gated by `ML_ADS_ENABLED` (the Cupones tab is part of
ML Ads). Its own pacer family, `order_discounts`, has a dedicated gate of 30 calls per minute (one call every
2 s, a quarter of the global 2/s), so the backfill never takes the budget of the other ML handlers and never
bursts. Runs of up to `PER_RUN` orders inside `RUN_BUDGET` follow each other `interval` apart, which keeps the
pace close to the gate (28.7 calls per minute measured with a simulated clock). The cursor is the data itself
(`services/ml_order_discounts/store.py`); the run summary lands in `worker_job_state.detail.last_result`.
"""

from __future__ import annotations

import logging
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Callable, Optional, Tuple

from app.core import database
from app.core.config import settings
from app.services.ml_ads.ingestion import BLOCKED, SessionFactory
from app.services.ml_order_discounts import ingestion
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.ml_publications import disabled_outcome, refresh

logger = logging.getLogger(__name__)

DISCOUNTS_HANDLER = "ml_orders.discounts"
RUN_BUDGET = timedelta(seconds=60)
PER_RUN = 30  # 60 s at the gate's one call every 2 s


class OrderDiscountsHandler:
    name = DISCOUNTS_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(seconds=5)  # the pause between runs of its own thread
    run_at_local: Optional[dtime] = None
    own_thread = True
    deadline_seconds = RUN_BUDGET.total_seconds() + 15  # the runtime's deadline must outlast the run budget

    def __init__(
        self,
        *,
        client_factory: Optional[Callable[[Pacer], MlHttpClient]] = None,
        pacer: Optional[Pacer] = None,
        session_factory: Optional[SessionFactory] = None,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.pacer = pacer or Pacer()
        self._client_factory = client_factory or (lambda pacer: MlHttpClient(pacer=pacer))
        self._client: Optional[MlHttpClient] = None
        self._session_factory: SessionFactory = session_factory or (lambda: database.get_background_db())
        self._now = now or (lambda: datetime.now(timezone.utc))

    def run(self, ctx: WorkerContext) -> JobResult:
        if not settings.ML_ADS_ENABLED:
            return disabled_outcome()
        if self._client is None:
            self._client = self._client_factory(self.pacer)
        deadline = min(ctx.deadline, self._now() + RUN_BUDGET)
        try:
            result = ingestion.run(
                self._session_factory,
                self._client,
                now=self._now,
                deadline=deadline,
                max_calls=PER_RUN,
                should_stop=ctx.stop_requested,
            )
        except Exception as exc:  # noqa: BLE001 -- the worker keeps running; the data is the cursor, the next run resumes
            logger.exception("order discounts run failed")
            error = f"{type(exc).__name__}: {exc}"[:300]
            return JobResult(success=False, detail={"error": error}, error=error)
        error = None
        if result.stopped == BLOCKED:
            error = "missing or rejected ML credentials"
        elif result.stopped == ingestion.TRANSPORT:
            error = f"no HTTP answer from ML: {result.transport_error}"
        return JobResult(success=True, detail=result.as_detail(), error=error)


# One in-process ML budget with the other handlers of this worker.
discounts = OrderDiscountsHandler(pacer=refresh.pacer)
