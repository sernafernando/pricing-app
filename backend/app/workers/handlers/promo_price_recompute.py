"""`promo_price.recompute` (promo-ml-precio-inmediato T1): recomputes the promo price columns of
the items ml-webhook just reported (`POST /api/promociones/recompute-precios`). No cron.

Runs in the ML worker (`ML_PUBLICATIONS_REGISTRY`): its pass reads the mlwebhook mirror, and the
sales worker must never wait on it. `own_thread` every 5 seconds, so a queued item is recomputed
within seconds and never waits behind a long ML handler (scan, sweep, verify) in the shared drain
pass; an empty queue costs one query. The pass itself (kill switch, per-item session, attempts and
parking, mirror outage) lives in `app.services.promo_price_recompute`.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import time, timedelta
from typing import Optional, Tuple

from app.services import promo_price_recompute
from app.workers.context import JobResult, WorkerContext


class PromoPriceRecomputeHandler:
    """`JobHandler` for `promo_price.recompute`."""

    name = "promo_price.recompute"
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(seconds=5)
    run_at_local: Optional[time] = None
    own_thread = True

    def run(self, ctx: WorkerContext) -> JobResult:
        result = promo_price_recompute.drain(deadline=ctx.deadline)
        return JobResult(
            success=not result.mirror_unavailable,
            detail=asdict(result),
            error="mlwebhook mirror unreadable" if result.mirror_unavailable else None,
        )


recompute = PromoPriceRecomputeHandler()
