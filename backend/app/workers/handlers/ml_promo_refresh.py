"""`ml_publications.promo_refresh`: refresh the promotions mirror of publications that became active again.

The owner's rule: promotions are asked about in ML only while the publication is active. The store sees the
reactivation (`status_activated` with `is_reactivation`) and queues the MLA in `promo_refresh_pending`
(`events_store.write_events`); this handler drains that queue through the same proxy call the panel's refresh
button uses (`ml_webhook_client.refresh_item_promotions`), which is what refreshes the mirror the panel reads.
No cron: it runs in the ML worker.

Gated by `promo_refresh.enabled` (default off, kill switch overrides) and by `promo_refresh.rate_per_min`.
The queue has one row per MLA, so a burst of notifications for one item is already one refresh and
`ML_PUB_PROMOTIONS_DEBOUNCE_SECONDS` (which collapses bursts of promotion notifications) is not needed here.
Each row is claimed alone, re-checked against the store right before the call (no longer active: dropped, no
call), refreshed OUTSIDE any DB session, then settled: deleted on success, dropped when retrying cannot help,
backed off on failure and quarantined after `promo_refresh_queue.MAX_ATTEMPTS`.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from app.core import database
from app.services import promo_refresh_queue as queue
from app.services.ml_publications import settings_store
from app.services.ml_publications.pacing import DEADLINE, Pacer
from app.services.ml_webhook_client import ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.ml_publications import disabled_outcome, refresh

logger = logging.getLogger(__name__)

PROMO_REFRESH_HANDLER = "ml_publications.promo_refresh"
PACER_FAMILY = "promo_refresh"
WINDOW_SECONDS = 60.0
_SETTING_KEYS = ("promo_refresh.enabled", "promo_refresh.rate_per_min")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PromoRefreshHandler:
    name = PROMO_REFRESH_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(seconds=15)
    run_at_local: Optional[dtime] = None

    def __init__(
        self,
        *,
        pacer: Optional[Pacer] = None,
        session_factory: Optional[Callable[[], Any]] = None,
        monotonic: Optional[Callable[[], float]] = None,
    ) -> None:
        self.pacer = pacer or Pacer()
        self._session_factory = session_factory or (lambda: database.get_background_db())
        self._monotonic = monotonic or time.monotonic
        self._calls: Deque[float] = deque()  # monotonic instants of the proxy calls of the last minute

    def _budget(self, per_minute: int) -> int:
        horizon = self._monotonic() - WINDOW_SECONDS
        while self._calls and self._calls[0] <= horizon:
            self._calls.popleft()
        return max(per_minute - len(self._calls), 0)

    def run(self, ctx: WorkerContext) -> JobResult:
        config = settings_store.get_settings(_SETTING_KEYS)
        if config["promo_refresh.enabled"].value is not True:
            return disabled_outcome()
        per_minute = config["promo_refresh.rate_per_min"].value
        detail: Dict[str, int] = {"refreshed": 0, "dropped": 0, "failed": 0, "quarantined": 0}
        stopped: Optional[str] = None
        while _utcnow() < ctx.deadline:
            if self._budget(per_minute) == 0:
                stopped = "rate_cap"
                break
            now = _utcnow()
            with self._session_factory() as db:
                mla = queue.claim_one(db, now)
                inactive = mla is not None and not queue.is_active(db, mla)
                if inactive:
                    queue.drop(db, mla)
            if mla is None:
                break
            if inactive:
                detail["dropped"] += 1
                continue
            if self.pacer.acquire(PACER_FAMILY, ctx.deadline) == DEADLINE:
                with self._session_factory() as db:
                    queue.release(db, mla, _utcnow())
                stopped = "deadline"
                break
            self._calls.append(self._monotonic())
            self._settle(mla, self._refresh(mla), detail)
        if stopped:
            detail["stopped"] = stopped  # type: ignore[assignment]
        return JobResult(success=True, detail=detail)

    @staticmethod
    def _refresh(mla: str):
        """The proxy call, outside any session. Never raises: an exception is a retryable failure."""
        try:
            return resolve_maybe_async(ml_webhook_client.refresh_item_promotions(mla))
        except Exception:  # noqa: BLE001 -- one MLA must not stop the others
            logger.warning("promo_refresh: refresh_item_promotions raised for %s", mla, exc_info=True)
            return None

    def _settle(self, mla: str, outcome, detail: Dict[str, int]) -> None:
        with self._session_factory() as db:
            if outcome is not None and outcome.ok:
                queue.drop(db, mla)
                detail["refreshed"] += 1
            elif outcome is not None and not outcome.reintentable:
                logger.warning("promo_refresh: %s dropped, retrying cannot help: %s", mla, outcome.motivo)
                queue.drop(db, mla)
                detail["dropped"] += 1
            else:
                result = queue.fail(db, mla, _utcnow())
                detail["failed"] += 1
                if result == queue.OUTCOME_QUARANTINED:
                    detail["quarantined"] += 1
                    logger.error("promo_refresh: %s QUARANTINED after %s attempts", mla, queue.MAX_ATTEMPTS)


# One in-process ML budget with the other handlers of this worker.
promo_refresh = PromoRefreshHandler(pacer=refresh.pacer)
