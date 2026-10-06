"""Job handlers of the ML publications store (design D1, D10, D12, D17, D19).

They run in their own worker process (`pricing-worker-ml.service`, registry
`ML_PUBLICATIONS_REGISTRY`), so ML pacing sleeps never delay the sales drain.

Every handler is gated by a DB-backed flag (`ml_pub_settings`, env default off,
`ML_PUB_KILL_SWITCH` overriding everything). A disabled handler returns the
disabled outcome BEFORE any queue read, ML call or write.
"""

from __future__ import annotations

import logging
from datetime import time, timedelta
from typing import Callable, Optional, Tuple

from app.services.ml_publications import settings_store
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

REFRESH_HANDLER = "ml_publications.refresh"


def disabled_outcome() -> JobResult:
    """The result of a handler whose flag is off (design D17).

    `success=False` on purpose: `WorkerRuntime._record_job_run` then writes only
    `last_run_at`, never `last_success_at`, so `scheduling.is_due` keeps the handler
    due and enabling it later runs it on the very next pass instead of tomorrow. A
    pending on-demand request flag also stays set (the runtime clears it on success only)."""
    return JobResult(success=False, detail={"disabled": True})


class RefreshHandler:
    """`ml_publications.refresh`: claims queued items and refreshes them from `/items/bulk`."""

    name = REFRESH_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(seconds=5)
    run_at_local: Optional[time] = None

    def __init__(
        self,
        *,
        client_factory: Optional[Callable[[Pacer], MlHttpClient]] = None,
        pacer: Optional[Pacer] = None,
    ) -> None:
        self.pacer = pacer or Pacer()
        self._client_factory = client_factory or (lambda pacer: MlHttpClient(pacer=pacer))

    def run(self, ctx: WorkerContext) -> JobResult:
        if not settings_store.is_enabled("refresh"):
            return disabled_outcome()
        return JobResult(success=True, detail={})


refresh = RefreshHandler()
