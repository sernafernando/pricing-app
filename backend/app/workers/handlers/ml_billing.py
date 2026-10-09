"""`ml_billing.sweep`: the billing lap as a worker handler, no cron (ml-billing-balance D12, BS-8).

Daily slot at 05:17 (the old cron's) plus a 15 s catch-up that stays active while the persisted
`worker_job_state.detail.complete` is False. Each run makes at most ONE proxy request
(`services/ml_billing/billing_lap.py`): the proxy answers 429 to anything faster than one call
per 15 s and ML enforces a hard 5 requests/minute per account, so the sweep of all periods
takes hours of ticks, never a blocked worker. The request spends a slot of the shared ML pacer.

`detail` is the lap cursor itself (the billing lap has no ML-side ledger). The tick runs under the
existing `cursor_name='billing'` lock, so a leftover cron run on the server is excluded.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from app.core import database
from app.core.config import settings
from app.models.worker_job_state import WorkerJobState
from app.services.ml_billing import billing_lap
from app.services.ml_billing.billing_sweep_service import CURSOR_NAME
from app.services.ml_orders_ingestion.sweep_service import (
    ensure_cursor_row,
    release_lock_as_error,
    release_lock_as_idle,
    try_acquire_run_lock,
)
from app.services.ml_publications.pacing import GRANTED, Pacer
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.ml_publications import disabled_outcome, refresh

logger = logging.getLogger(__name__)

BILLING_HANDLER = "ml_billing.sweep"
CATCH_UP = billing_lap.SPACING
PACER_FAMILY = "billing"


class BillingHandler:
    name = BILLING_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = time(5, 17)
    catch_up_interval: Optional[timedelta] = CATCH_UP

    def __init__(
        self,
        *,
        pacer: Optional[Pacer] = None,
        session_factory: Optional[Callable[[], Any]] = None,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.pacer = pacer or Pacer()
        self._session_factory = session_factory or (lambda: database.get_background_db())
        self._now = now or (lambda: datetime.now(timezone.utc))

    def run(self, ctx: WorkerContext) -> JobResult:
        if not settings.ML_BILLING_ENABLED:
            return disabled_outcome()
        now = self._now()
        with self._session_factory() as db:
            ensure_cursor_row(db, cursor_name=CURSOR_NAME)
            acquired = try_acquire_run_lock(db, now, cursor_name=CURSOR_NAME)
        if not acquired:
            # A leftover cron run (or a stale tick) holds the lock: leave the lap as it is and let the catch-up retry.
            return JobResult(success=True, detail=self._save(lambda state: {**state, "complete": False}))
        try:
            if self.pacer.acquire(PACER_FAMILY, ctx.deadline) != GRANTED:
                release_lock_as_idle(now, complete=False, cursor_name=CURSOR_NAME)
                return JobResult(success=True, detail=self._save(lambda state: {**state, "complete": False}))
            detail = self._save_state(self._tick(self._load(), now))
        except Exception as exc:  # noqa: BLE001 -- the worker keeps running; the lap resumes from `detail`
            logger.exception("billing tick failed")
            release_lock_as_error(exc, cursor_name=CURSOR_NAME)
            error = f"{type(exc).__name__}: {exc}"[:300]
            detail = self._save(lambda state: {**state, "complete": False, "error": error})
            return JobResult(success=True, detail=detail, error=error)
        release_lock_as_idle(now, complete=bool(detail.get("complete")), cursor_name=CURSOR_NAME)
        return JobResult(success=True, detail=detail)

    def _tick(self, state: Dict[str, Any], now: datetime) -> Dict[str, Any]:
        with self._session_factory() as db:
            return billing_lap.run_billing_tick(db, state, now)

    def _load(self) -> Dict[str, Any]:
        with self._session_factory() as db:
            row = db.get(WorkerJobState, self.name)
            return dict(row.detail or {}) if row is not None else {}

    def _save_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Writes the lap state in its own short block (single worker, one writer): never held across the proxy call."""
        state = {**state, "at": self._now().isoformat()}
        with self._session_factory() as db:
            row = db.get(WorkerJobState, self.name)
            if row is None:
                db.add(WorkerJobState(name=self.name, detail=state))
            else:
                row.detail = state
        return state

    def _save(self, change: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
        return self._save_state(change(self._load()))


# One in-process ML budget with the other handlers of this worker.
billing = BillingHandler(pacer=refresh.pacer)
