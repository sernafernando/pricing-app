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
from typing import Any, Dict, Optional, Set


@dataclass(frozen=True)
class WorkerContext:
    """Passed to `JobHandler.run` on every invocation.

    `deadline`: wall-clock instant a handler must stop starting new work by
    (design D5's `ctx.deadline` -- a long job yields between batches so the
    drain stays responsive). A handler that owns its own DB work always uses
    short `get_background_db()` blocks (design D4 "DB sessions" rule);
    `WorkerContext` never carries a `Session`.

    `held_tokens`: the SAME mutable set object `WorkerRuntime` feeds its
    `HeartbeatThread.token_provider` (design D4 step 5 / PR3.T6a). A handler
    that claims dirty rows (currently only `order_metrics.drain`) adds each
    claim's token string here right after claiming and removes it right
    after that claim is released/stored/failed, so the heartbeat renews
    every lease this process actually still holds. `None` when the runtime
    was built without heartbeat wiring (e.g. a bare unit test) -- handlers
    must tolerate that.
    """

    deadline: datetime
    worker_name: str = "worker"
    held_tokens: Optional[Set[str]] = None


@dataclass(frozen=True)
class JobResult:
    """Returned by `JobHandler.run`. `success=False` does not raise --
    the runtime logs `detail` and lets the handler's own next scheduled
    run or notify wake retry it, same failure-isolation shape as the
    per-order fencing in `order_metrics.queue` (design D5)."""

    success: bool
    detail: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
