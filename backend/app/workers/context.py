"""`WorkerContext`/`JobResult` (design D6) -- the shared shapes a `JobHandler`
receives from/returns to the runtime.

PR2 ships an idle runtime with an EMPTY `registry.py`, so nothing calls
`JobHandler.run` yet -- these types exist so PR3's `order_metrics.drain`
handler (and the runtime that drives it) have a stable, already-tested
contract to implement against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class WorkerContext:
    """Passed to `JobHandler.run` on every invocation.

    `deadline`: wall-clock instant a handler must stop starting new work by
    (design D5's `ctx.deadline` -- a long job yields between batches so the
    drain stays responsive). A handler that owns its own DB work always uses
    short `get_background_db()` blocks (design D4 "DB sessions" rule);
    `WorkerContext` never carries a `Session`.
    """

    deadline: datetime
    worker_name: str = "worker"


@dataclass(frozen=True)
class JobResult:
    """Returned by `JobHandler.run`. `success=False` does not raise --
    the runtime logs `detail` and lets the handler's own next scheduled
    run or notify wake retry it, same failure-isolation shape as the
    per-order fencing in `order_metrics.queue` (design D5)."""

    success: bool
    detail: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
