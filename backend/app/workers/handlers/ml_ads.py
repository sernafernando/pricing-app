"""`ml_ads.ingest`: the Product Ads backfill (ml-billing-balance, ADS-5, ADS-7, D3).

Scheduled by the existing worker, no cron: a daily slot at 10:30 (after ML's 10:00 GMT-3 refresh of the
previous day) plus a 60 s catch-up that stays active while the persisted `worker_job_state.detail.complete`
is False. A run spends at most `RUN_BUDGET` on calls, about 25% of the shared pacer, so the backfill
(about 110 calls per advertiser-day) takes several hours without starving `ml_publications.*`.

The cursor is the ledger (`services/ml_ads/schedule.py`); `detail` only carries the run summary and the
`complete` flag, so deleting it loses no progress.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core import database
from app.core.config import settings
from app.models.worker_job_state import WorkerJobState
from app.services.ml_ads import schedule
from app.services.ml_ads.ingestion import BLOCKED, SessionFactory
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.ml_publications import disabled_outcome, refresh

logger = logging.getLogger(__name__)

ADS_HANDLER = "ml_ads.ingest"
RUN_BUDGET = timedelta(seconds=15)
CATCH_UP = timedelta(seconds=60)


class AdsHandler:
    name = ADS_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = time(10, 30)
    catch_up_interval: Optional[timedelta] = CATCH_UP

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
        budget_until = min(ctx.deadline, self._now() + RUN_BUDGET)
        try:
            tick = schedule.run_tick(self._session_factory, self._client, now=self._now, deadline=budget_until)
        except Exception as exc:  # noqa: BLE001 -- the worker keeps running; the ledger resumes the next run
            logger.exception("ads run failed")
            error = f"{type(exc).__name__}: {exc}"[:300]
            # A success with `complete` False: the 60 s catch-up retries it without the runtime spinning on a failure.
            return JobResult(success=True, detail=self._flush({"complete": False, "error": error}), error=error)
        if tick.stopped == BLOCKED:
            logger.error("ads blocked: missing or rejected credentials")
        return JobResult(success=True, detail=self._flush(tick.as_detail()))

    def _flush(self, detail: Dict[str, Any]) -> Dict[str, Any]:
        detail = {**detail, "at": self._now().isoformat()}
        with self._session_factory() as db:
            stmt = pg_insert(WorkerJobState).values(name=self.name, detail=detail)
            db.execute(stmt.on_conflict_do_update(index_elements=["name"], set_={"detail": stmt.excluded.detail}))
        return detail


# One in-process ML budget with the other handlers of this worker.
ads = AdsHandler(pacer=refresh.pacer)
