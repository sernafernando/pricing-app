"""`para_ganar.consulta`: drains consultation jobs (refresh catalog → P5).

Runs in the ML publications worker (`ML_PUBLICATIONS_REGISTRY`) because each MLA
hits MercadoLibre via `refrescar_competencia_catalogo`. Woken by
`pg_notify('para_ganar_consulta')` plus a 30 s safety interval (same shape as
`promo_write.refresh`).
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Optional, Tuple

from app.services import para_ganar_consulta as consulta
from app.workers.context import JobResult, WorkerContext


class ParaGanarConsultaHandler:
    """`JobHandler` for `para_ganar.consulta`."""

    name = "para_ganar.consulta"
    channels: Tuple[str, ...] = (consulta.CHANNEL,)
    interval: Optional[timedelta] = timedelta(seconds=30)
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        return JobResult(success=True, detail=consulta.drain(deadline=ctx.deadline))


para_ganar_consulta = ParaGanarConsultaHandler()
