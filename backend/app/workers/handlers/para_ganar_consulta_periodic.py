"""`para_ganar.consulta_periodic`: every 2h enqueue Periodicidad MLAs into the shared drain.

Does not call ML itself — only inserts a `source=periodic` job (unless one is still
open or the inclusion set is empty). The existing `para_ganar.consulta` handler
drains refresh → P5 per MLA.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Optional, Tuple

from app.core.database import get_background_db
from app.services import para_ganar_consulta as consulta
from app.workers.context import JobResult, WorkerContext


class ParaGanarConsultaPeriodicHandler:
    """`JobHandler` for `para_ganar.consulta_periodic`."""

    name = "para_ganar.consulta_periodic"
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = consulta.PERIODIC_INTERVAL
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        with get_background_db() as db:
            job = consulta.enqueue_periodic_consulta(db)
            if job is None:
                return JobResult(success=True, detail={"enqueued": False, "reason": "skipped_or_empty"})
            return JobResult(
                success=True,
                detail={
                    "enqueued": True,
                    "job_id": job.id,
                    "total_count": job.total_count,
                },
            )


para_ganar_consulta_periodic = ParaGanarConsultaPeriodicHandler()
