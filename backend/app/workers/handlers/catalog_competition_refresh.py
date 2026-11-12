"""`ml_publications.catalog_competition_refresh`: drain catalog-competition refresh queue.

When `hay_mejores_ofertas` is newly set, the promotions store enqueues the MLA into
`catalog_competition_refresh_pending`. This handler persists a fresh
`ml_catalog_competition` snapshot via `refrescar_competencia_catalogo` (same path as the
panel's refresh button). No UI; runs in the ML worker.

Gated by `catalog_competition_refresh.enabled` (kill switch overrides) and
`catalog_competition_refresh.rate_per_min`. Shares the in-process ML `Pacer` with the
other ML handlers. Inactive MLAs are dropped without calling the proxy.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from app.core import database
from app.services import catalog_competition_refresh_queue as queue
from app.services.ml_catalog_competition_service import refrescar_competencia_catalogo
from app.services.ml_publications import settings_store
from app.services.ml_publications.pacing import DEADLINE, Pacer
from app.services.promo_refresh_queue import is_active
from app.utils.async_bridge import resolve_maybe_async
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.ml_publications import disabled_outcome, refresh

logger = logging.getLogger(__name__)

HANDLER_NAME = "ml_publications.catalog_competition_refresh"
PACER_FAMILY = "catalog_competition_refresh"
WINDOW_SECONDS = 60.0
_SETTING_KEYS = (
    "catalog_competition_refresh.enabled",
    "catalog_competition_refresh.rate_per_min",
)

# Settlement tokens from `_refresh`.
_OK = "ok"
_NOT_CATALOG = "not_catalog"
_ERROR = "error"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CatalogCompetitionRefreshHandler:
    name = HANDLER_NAME
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(seconds=30)
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
        self._calls: Deque[float] = deque()

    def _budget(self, per_minute: int) -> int:
        horizon = self._monotonic() - WINDOW_SECONDS
        while self._calls and self._calls[0] <= horizon:
            self._calls.popleft()
        return max(per_minute - len(self._calls), 0)

    def run(self, ctx: WorkerContext) -> JobResult:
        config = settings_store.get_settings(_SETTING_KEYS)
        if config["catalog_competition_refresh.enabled"].value is not True:
            return disabled_outcome()
        per_minute = config["catalog_competition_refresh.rate_per_min"].value
        detail: Dict[str, Any] = {"refreshed": 0, "dropped": 0, "failed": 0, "quarantined": 0}
        stopped: Optional[str] = None
        while _utcnow() < ctx.deadline:
            if self._budget(per_minute) == 0:
                stopped = "rate_cap"
                break
            now = _utcnow()
            with self._session_factory() as db:
                claim = queue.claim_one(db, now)
                inactive = claim is not None and not is_active(db, claim.mla)
                if claim is not None and inactive:
                    queue.drop(db, claim)
            if claim is None:
                break
            if inactive:
                detail["dropped"] += 1
                continue
            if self.pacer.acquire(PACER_FAMILY, ctx.deadline) == DEADLINE:
                with self._session_factory() as db:
                    queue.release(db, claim, _utcnow())
                stopped = "deadline"
                break
            self._calls.append(self._monotonic())
            self._settle(claim, self._refresh(claim.mla), detail)
        if stopped:
            detail["stopped"] = stopped
        return JobResult(success=True, detail=detail)

    def _refresh(self, mla: str) -> str:
        """Persist one snapshot. Never raises.

        `refrescar_competencia_catalogo` does not raise on fetch failure: it stores a
        row with `fetch_status` in {ok, not_catalog, error}. Only `ok` settles as
        success; `not_catalog` is dropped (retry cannot help); `error` reschedules.
        """
        try:
            # Read the status while the session is open: the factory commits on exit,
            # which expires the ORM rows, and touching them detached raises
            # DetachedInstanceError (it settled as `error` and quarantined the MLA).
            with self._session_factory() as db:
                rows = resolve_maybe_async(refrescar_competencia_catalogo(db, [mla]))
                raw_status = rows[0].fetch_status if rows else None
            if not rows:
                return _ERROR
            status = (raw_status or _ERROR).lower()
            if status == _OK:
                return _OK
            if status == _NOT_CATALOG:
                return _NOT_CATALOG
            return _ERROR
        except Exception:  # noqa: BLE001
            logger.warning("catalog_competition_refresh: refresh failed for %s", mla, exc_info=True)
            return _ERROR

    def _settle(self, claim: queue.Claim, outcome: str, detail: Dict[str, Any]) -> None:
        with self._session_factory() as db:
            if outcome == _OK:
                queue.drop(db, claim)
                detail["refreshed"] += 1
            elif outcome == _NOT_CATALOG:
                logger.info("catalog_competition_refresh: %s dropped (not_catalog)", claim.mla)
                queue.drop(db, claim)
                detail["dropped"] += 1
            else:
                result = queue.fail(db, claim, _utcnow())
                detail["failed"] += 1
                if result == queue.OUTCOME_QUARANTINED:
                    detail["quarantined"] += 1
                    logger.error(
                        "catalog_competition_refresh: %s QUARANTINED after %s attempts",
                        claim.mla,
                        queue.MAX_ATTEMPTS,
                    )


catalog_competition_refresh = CatalogCompetitionRefreshHandler(pacer=refresh.pacer)
