"""Publication repair jobs on pricing-worker-ml (envio + sku).

Condition: linked `publicaciones_ml` × `ml_items` drift. Shares the store Pacer
so 429/AIMD applies like the rest of the ML publications workers — not a FastAPI
background tick and not the sync_full cron.
"""

from __future__ import annotations

import logging
from datetime import time, timedelta
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.models.publicacion_repair import TRIGGER_TICK
from app.services.ml_publications.pacing import GRANTED, Pacer
from app.services.publicacion_repair.envio import run_envio_repair
from app.services.publicacion_repair.sku import run_sku_repair
from app.utils.async_bridge import resolve_maybe_async
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.ml_publications import disabled_outcome, refresh

logger = logging.getLogger(__name__)

ENVIO_HANDLER = "publicacion_repair.envio"
SKU_HANDLER = "publicacion_repair.sku"
PACER_FAMILY_ENVIO = "publicacion_repair_envio"
PACER_FAMILY_SKU = "publicacion_repair_sku"


def _gates_open() -> Optional[str]:
    if settings.ML_PUB_KILL_SWITCH:
        return "ML_PUB_KILL_SWITCH=true"
    if not settings.ML_ITEM_DATA_WRITE_ENABLED:
        return "ML_ITEM_DATA_WRITE_ENABLED=false"
    return None


class EnvioRepairHandler:
    """`publicacion_repair.envio`: ME2/pickup/Flex drift repair under the shared Pacer."""

    name = ENVIO_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(minutes=5)
    run_at_local: Optional[time] = None

    def __init__(self, *, pacer: Optional[Pacer] = None) -> None:
        self.pacer = pacer or refresh.pacer

    def run(self, ctx: WorkerContext) -> JobResult:
        blocked = _gates_open()
        if blocked is not None:
            logger.info("%s disabled: %s", self.name, blocked)
            return disabled_outcome()

        def before_write() -> bool:
            if ctx.stop_requested():
                return False
            outcome = self.pacer.acquire(
                PACER_FAMILY_ENVIO,
                deadline=ctx.deadline,
                should_stop=ctx.stop_requested,
            )
            return outcome == GRANTED

        def on_rate_limited(retry_after: Optional[str]) -> None:
            self.pacer.on_rate_limited(PACER_FAMILY_ENVIO, retry_after)

        stats: Dict[str, Any] = resolve_maybe_async(
            run_envio_repair(
                trigger=TRIGGER_TICK,
                before_write=before_write,
                on_rate_limited=on_rate_limited,
                pacing_seconds=0,
            )
        )
        return JobResult(success=True, detail=stats)


class SkuRepairHandler:
    """`publicacion_repair.sku`: SELLER_SKU vs ERP codigo under the shared Pacer."""

    name = SKU_HANDLER
    channels: Tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(minutes=5)
    run_at_local: Optional[time] = None

    def __init__(self, *, pacer: Optional[Pacer] = None) -> None:
        self.pacer = pacer or refresh.pacer

    def run(self, ctx: WorkerContext) -> JobResult:
        blocked = _gates_open()
        if blocked is not None:
            logger.info("%s disabled: %s", self.name, blocked)
            return disabled_outcome()

        def before_write() -> bool:
            if ctx.stop_requested():
                return False
            outcome = self.pacer.acquire(
                PACER_FAMILY_SKU,
                deadline=ctx.deadline,
                should_stop=ctx.stop_requested,
            )
            return outcome == GRANTED

        stats: Dict[str, Any] = resolve_maybe_async(
            run_sku_repair(
                trigger=TRIGGER_TICK,
                before_write=before_write,
                pacing_seconds=0,
            )
        )
        return JobResult(success=True, detail=stats)


envio_repair = EnvioRepairHandler()
sku_repair = SkuRepairHandler()
