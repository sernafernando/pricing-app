"""`promo_write.refresh`: drains `promo_refresh_pending`, the follow-up refresh a promo write queues ~60 s out.

No cron: it runs every 30 seconds in the ML worker (`ML_PUBLICATIONS_REGISTRY`), whose handlers make ML calls
and may wait on them; the sales worker must never wait on ml-webhook. A row due at +60 s is refreshed within
60-90 s of the write. The pass itself (stale purge, bounded batch, attempts and backoff, no session held across
the HTTP call) lives in `app.services.promo_refresh_drain`, shared with the manual script.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Optional, Tuple

from app.services import promo_refresh_drain
from app.workers.context import JobResult, WorkerContext


class PromoWriteRefreshHandler:
    """`JobHandler` for `promo_write.refresh`."""

    name = "promo_write.refresh"
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(seconds=30)
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        return JobResult(success=True, detail=promo_refresh_drain.drain(deadline=ctx.deadline))


promo_write_refresh = PromoWriteRefreshHandler()
