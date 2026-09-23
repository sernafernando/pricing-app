"""Pure scheduling math for `JobHandler` (design D6): decides whether a job
is due, given only `now` and its `worker_job_state.last_success_at`. No DB
access here on purpose -- the runtime reads `last_success_at` and calls
`is_due`, so this module stays trivially unit-testable (PR2.T1) and free of
any `get_background_db()` short-block concerns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol
from zoneinfo import ZoneInfo

ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


class _SchedulableHandler(Protocol):
    """Structural subset of `registry.JobHandler` this module needs --
    avoids a circular import (`registry.py` does not need to import this
    module's types, only call `is_due`)."""

    interval: Optional[object]
    run_at_local: Optional[object]


def is_due(handler: _SchedulableHandler, *, now: datetime, last_success_at: Optional[datetime]) -> bool:
    """Whether `handler` should run right now.

    - `interval` jobs (e.g. `order_metrics.reconcile`, every 10 min): due
      when never succeeded, or when `now - last_success_at >= interval`.
    - `run_at_local` jobs (e.g. `order_metrics.divergence`, daily 04:00 AR):
      due once local wall-clock time reaches today's slot AND the last
      success was not already at-or-after that slot -- this is the
      restart-does-not-double-run guarantee (design D6): a worker
      restarting at 04:05 after already succeeding at 04:01 today must not
      re-run, but a fresh day (or an earlier on-demand success before
      today's slot) must still let it run.
    - A handler with neither (channel/notify-only, e.g. `order_metrics.drain`
      in PR3) is never due by schedule -- it only runs on LISTEN wake or the
      runtime's safety poll.
    """
    if handler.interval is not None:
        if last_success_at is None:
            return True
        return (now - last_success_at) >= handler.interval

    if handler.run_at_local is not None:
        local_now = now.astimezone(ARGENTINA_TZ)
        slot_today = local_now.replace(
            hour=handler.run_at_local.hour,
            minute=handler.run_at_local.minute,
            second=0,
            microsecond=0,
        )
        if local_now < slot_today:
            return False
        if last_success_at is None:
            return True
        local_last_success = last_success_at.astimezone(ARGENTINA_TZ)
        return local_last_success < slot_today

    return False
