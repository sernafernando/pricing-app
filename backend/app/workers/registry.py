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
from app.workers.handlers.order_metrics import divergence as _order_metrics_divergence
from app.workers.handlers.order_metrics import drain as _order_metrics_drain
from app.workers.handlers.order_metrics import reconcile as _order_metrics_reconcile


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
REGISTRY: List[JobHandler] = [_order_metrics_drain, _order_metrics_reconcile, _order_metrics_divergence]
