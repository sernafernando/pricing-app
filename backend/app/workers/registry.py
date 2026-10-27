"""`JobHandler` Protocol + the explicit handler list (design D6).

PR2 ships this registry EMPTY on purpose: the runtime (`runtime.py`) is
fully generic and already wired to LISTEN, safety-poll, and schedule
handlers by `interval`/`run_at_local` (via `scheduling.is_due`), but no
concrete job exists yet -- an idle worker with an empty registry is the
whole PR2 deliverable (design Migration/Rollout: infra lands inert before
PR3 registers `order_metrics.drain`). No auto-discovery: a handler only
runs if it is appended here explicitly.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import List, Optional, Protocol, Tuple

from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.combos_sync import sync as _combos_sync
from app.workers.handlers.ml_orders_quarantine import quarantine_retry as _ml_orders_quarantine_retry
from app.workers.handlers.order_metrics import divergence as _order_metrics_divergence
from app.workers.handlers.order_metrics import drain as _order_metrics_drain
from app.workers.handlers.order_metrics import reconcile as _order_metrics_reconcile
from app.workers.handlers.rrhh_horas_extras import horas_extras as _rrhh_horas_extras
from app.workers.handlers.sell_drain import drain as _sell_drain
from app.workers.handlers.sell_in_bono import bono as _sell_in_bono
from app.workers.handlers.sell_out_drain import drain as _sell_out_drain
from app.workers.handlers.tp_cost_fill import fill as _tp_cost_fill


class JobHandler(Protocol):
    """One schedulable/notifiable unit of worker work (design D6)."""

    name: str
    """Unique key, also the `worker_job_state.name` row this handler's
    schedule/liveness state is persisted under (e.g. `'order_metrics.drain'`)."""

    channels: Tuple[str, ...]
    """LISTEN channel names that wake this handler. `()` = schedule-only
    (e.g. `order_metrics.reconcile`, `order_metrics.divergence`)."""

    interval: Optional[timedelta]
    """Periodic schedule (e.g. every 10 minutes). `None` if not interval-based."""

    run_at_local: Optional[time]
    """Daily wall-clock slot in `scheduling.ARGENTINA_TZ`. `None` if not
    daily-scheduled."""

    def run(self, ctx: WorkerContext) -> JobResult:
        """Must use short `get_background_db()` blocks (never hold a Session
        across the whole call) and respect `ctx.deadline` by yielding between
        batches, per design D4/D5."""
        ...


# Explicit, ordered list -- no auto-discovery. PR3 appends
# `order_metrics.drain`; PR6 appends `order_metrics.reconcile` and
# `order_metrics.divergence`.
# metricas-ml-tplink-mode P2 appends `tp_cost.fill` (notify-driven, like the drain).
# sell-in-sell-out T4 appends `sell.drain` (notify-driven); since T5 it recomputes the sell-in allocation.
# combos-propios C1 appends `combos.sync` (every 30 minutes; replaces the ERP cron for combos).
# rrhh-horas-extras appends `rrhh.horas_extras` (daily 03:30; replaces the never-installed HE crontab entry).
# remove-ml-divergences appends `ml_orders.quarantine_retry` (notify-driven; retries failed ML order writes).
# sell-in-sell-out T3c-3 appends `sell_in.bono` (notify-driven; applies brand bonuses to invoiced purchases).
# sell-in-sell-out T7 S3 appends `sell_out.drain` (notify-driven; rebuilds the queued sell-out campaigns).
REGISTRY: List[JobHandler] = [
    _order_metrics_drain,
    _order_metrics_reconcile,
    _order_metrics_divergence,
    _tp_cost_fill,
    _sell_drain,
    _combos_sync,
    _rrhh_horas_extras,
    _ml_orders_quarantine_retry,
    _sell_in_bono,
    _sell_out_drain,
]

# The ML publications store runs in its OWN process (`pricing-worker-ml.service`,
# `--registry ml_publications`, design D1): its handlers sleep for ML pacing and must
# never delay `order_metrics.drain`. A separate explicit list, never merged into REGISTRY.
#
# Resolved lazily (PEP 562) so the sales worker, which imports this module, never imports the ML
# handlers: an import failure there must not take `pricing-worker` down with it.
_ml_publications_registry: Optional[List[JobHandler]] = None


def __getattr__(name: str) -> List[JobHandler]:
    global _ml_publications_registry
    if name == "ML_PUBLICATIONS_REGISTRY":
        if _ml_publications_registry is None:
            from app.workers.handlers.ml_ads import ads
            from app.workers.handlers.ml_billing import billing
            from app.workers.handlers.ml_promo_refresh import promo_refresh
            from app.workers.handlers.ml_publications import (
                freshness,
                intake,
                missed_feeds,
                refresh,
                relink,
                scan,
                sweep,
                verify,
            )
            from app.workers.handlers.promo_refresh import promo_write_refresh

            _ml_publications_registry = [
                refresh,
                intake,
                relink,
                scan,
                missed_feeds,
                sweep,
                verify,
                promo_refresh,
                ads,
                # promo-write-refresh P2: the ~60 s follow-up refresh after a promo write (was an unscheduled script).
                promo_write_refresh,
                # ml-sync-pipeline S5: the per-minute freshness check (no ML call).
                freshness,
                billing,
            ]
        return _ml_publications_registry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
