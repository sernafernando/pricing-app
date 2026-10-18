"""`combos.sync` (combos-propios C1): keeps `combo_componentes` in step with
the combo source. No cron.

Schedule-only (`channels=()`), every 30 minutes. A run fetches the FULL
snapshot from the source adapter (today the ERP, `fuente_erp.fetch_snapshot`)
with no database session open, then reconciles it against the stored rows and
applies the plan in ONE short `get_background_db()` transaction, so readers
never see a half-applied snapshot. A fetch that fails or comes back
untrustworthy writes nothing (`success=False`); the next interval retries. An
empty or truncated snapshot (the reconcile's completeness floor) applies its
inserts and updates but no deletions, and also reports `success=False`.

It shares the main worker with `order_metrics.drain`, so the fetch (one blocking
HTTP call) is bounded by `ctx.deadline`: its wall-clock budget is the time left,
capped at `FETCH_TIMEOUT_SECONDS`, and the adapter returns or raises within it
even against a server that drips bytes. With under `MIN_FETCH_SECONDS` left the run does
nothing and the next interval runs it. The apply always follows a fetch that
returned, since dropping a fetched snapshot would only repeat the same call.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta

from app.core.database import get_background_db
from app.services.combos import store
from app.services.combos.fuente_erp import fetch_snapshot
from app.services.combos.reconcile import plan_full
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

# Longest the fetch may block the main worker (the full ERP list is ~2k rows).
FETCH_TIMEOUT_SECONDS = 30
# Under this much time left before `ctx.deadline`, a fetch is not worth starting.
MIN_FETCH_SECONDS = 5


class CombosSyncHandler:
    """`JobHandler` for `combos.sync`."""

    name = "combos.sync"
    channels: tuple[str, ...] = ()
    interval: timedelta | None = timedelta(minutes=30)
    run_at_local: time | None = None

    def run(self, ctx: WorkerContext) -> JobResult:
        remaining = (ctx.deadline - datetime.now(UTC)).total_seconds()
        if remaining < MIN_FETCH_SECONDS:
            return JobResult(success=True, detail={"skipped": "deadline"})
        try:
            snapshot = fetch_snapshot(timeout=min(FETCH_TIMEOUT_SECONDS, remaining))
        except Exception as exc:  # the source is outside our control: log, write nothing, retry next interval
            logger.warning("combos.sync: snapshot fetch failed, nothing written: %s", exc)
            return JobResult(success=False, error=f"{type(exc).__name__}: {exc}")

        with get_background_db() as db:
            plan = plan_full(snapshot, store.load_current(db))
            counts = store.apply(db, plan)

        detail = {"combos": len(snapshot), **counts, "deletions_skipped": plan.deletions_skipped}
        if plan.deletions_skipped:
            # Empty or truncated snapshot: inserts/updates applied, absences not trusted. Not a success:
            # the source looked broken, and a silent green run would hide that combos stopped syncing.
            logger.warning("combos.sync: deletions skipped, snapshot looked incomplete: %s", detail)
            return JobResult(
                success=False,
                detail=detail,
                error=f"deletions skipped: the snapshot brings {len(snapshot)} combos, too few against the stored ones",
            )
        if not plan.is_empty:
            logger.info("combos.sync: %s", detail)
        return JobResult(success=True, detail=detail)


sync = CombosSyncHandler()
