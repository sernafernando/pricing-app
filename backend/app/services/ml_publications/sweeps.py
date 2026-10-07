"""Sweeps of the resources with no notification topic: performance and visits (design D17).

Every tick (the handler runs every 10 minutes) takes, per resource, the K items whose state is oldest
(`last_checked_at`, never-checked first) among the eligible ones and enqueues them in the sweep lane with the
resource NAMED (`{performance}` / `{visits}`: they are `bundle.SWEEP_ONLY`, so only a named request fetches
them). K = ceil(eligible / 144): 144 ticks a day cover every eligible item once a day. The sweep makes no ML
call and spends no budget of its own: the refresh handler fetches what it enqueued, under the shared pacer
and the lane order.

Eligible: status in `sweep.statuses` (never `closed`), not gone, never-existed excluded; a performance state
stored as `applicable = false` (a catalog product item answers "not supported") only after
`ML_PUB_NOT_APPLICABLE_RECHECK_DAYS`. Only resources named in `bundle_resources` are swept: a name that is not
listed would be dropped by the refresh handler and the item selected again on every tick.

The tick yields while live work exists (manual or notification lane entries ready to be claimed), skips
items that already have a queue entry (a re-enqueue would bump a claim in flight) and stops adding work while
earlier sweep entries have not been fetched (`BACKLOG_TICKS` ticks' worth), so a stopped refresh handler cannot
make the queue grow without bound. Every tick leaves a run record.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from sqlalchemy import text

from app.core import database
from app.core.config import SCAN_STATUS_NAMES
from app.models.ml_publications import MlPubJobRun
from app.services.ml_publications import queue
from app.services.ml_publications.resources import ITEM_KIND, PERFORMANCE_RESOURCE, VISITS_RESOURCE

logger = logging.getLogger(__name__)

JOB = "sweep"
# The handler interval is 10 minutes: this many ticks make a day.
TICKS_PER_DAY = 144
# Sweep entries allowed to wait unfetched, in ticks' worth of the current batch size.
BACKLOG_TICKS = 3
STATEMENT_TIMEOUT = "20s"

OUTCOME_SUCCESS = "success"
OUTCOME_YIELDED = "yielded"
OUTCOME_BACKLOG = "backlog"
OUTCOME_NO_RESOURCES = "no_resources"
OUTCOME_FAILED = "failed"

# Resource name -> its state table. Fixed identifiers: never built from input.
_TABLES: Mapping[str, str] = {PERFORMANCE_RESOURCE: "ml_item_performance", VISITS_RESOURCE: "ml_item_visits"}
SWEEP_RESOURCES = tuple(_TABLES)

_ELIGIBLE = """
    FROM ml_items i
    LEFT JOIN {table} s ON s.item_id = i.item_id
    WHERE i.status = ANY(CAST(:statuses AS text[])) AND i.status <> 'closed'
      AND i.gone_at IS NULL AND i.never_existed IS NOT TRUE
      {not_applicable}
"""
# Performance only: a stored "not applicable" answer is rechecked at the long interval.
_NOT_APPLICABLE = (
    "AND (s.applicable IS DISTINCT FROM FALSE OR s.last_checked_at IS NULL OR s.last_checked_at < :recheck_before)"
)
_NOT_QUEUED = "AND NOT EXISTS (SELECT 1 FROM ml_pub_refresh_queue q WHERE q.kind = 'item' AND q.entity_id = i.item_id)"

_LIVE_WORK = text(
    "SELECT 1 FROM ml_pub_refresh_queue WHERE lane <= :lane AND claimed_at IS NULL AND parked_at IS NULL "
    "AND not_before <= now() LIMIT 1"
)
_SWEEP_BACKLOG = text("SELECT count(*) FROM ml_pub_refresh_queue WHERE lane = :lane AND parked_at IS NULL")


def batch_size(eligible: int) -> int:
    """K: items per resource per tick so that a day of ticks covers every eligible item once."""
    return math.ceil(eligible / TICKS_PER_DAY) if eligible > 0 else 0


def daily_calls(*eligible_per_resource: int) -> int:
    """ML calls a day the sweep asks for: one per selected item and resource, `batch * ticks` each."""
    return sum(batch_size(eligible) * TICKS_PER_DAY for eligible in eligible_per_resource)


def requests_per_second(calls_per_day: float) -> float:
    return calls_per_day / 86_400


def sweep_statuses(setting_value: Any) -> List[str]:
    """The statuses a `sweep.statuses` value covers: known scan statuses, `closed` never."""
    if not isinstance(setting_value, (list, tuple)):
        return []
    return [s for s in dict.fromkeys(setting_value) if s in SCAN_STATUS_NAMES and s != "closed"]


@dataclass
class ResourceTick:
    eligible: int = 0
    batch: int = 0
    selected: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {"eligible": self.eligible, "batch": self.batch, "selected": self.selected}


@dataclass
class SweepResult:
    outcome: str = OUTCOME_SUCCESS
    error: Optional[str] = None
    enqueued: int = 0
    resources: Dict[str, ResourceTick] = field(default_factory=dict)

    def counts(self) -> Dict[str, Any]:
        calls = daily_calls(*(t.eligible for t in self.resources.values()))
        return {
            "enqueued": self.enqueued,
            "resources": {name: tick.as_dict() for name, tick in self.resources.items()},
            "calls_per_day": calls,
            "requests_per_second": round(requests_per_second(calls), 4),
        }

    def as_detail(self) -> Dict[str, Any]:
        detail: Dict[str, Any] = {"outcome": self.outcome, **self.counts()}
        if self.error:
            detail["error"] = self.error
        return detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _eligible_sql(resource: str) -> str:
    return _ELIGIBLE.format(
        table=_TABLES[resource], not_applicable=_NOT_APPLICABLE if resource == PERFORMANCE_RESOURCE else ""
    )


def _tick(
    statuses: Sequence[str], resources: Sequence[str], recheck_before: datetime, result: SweepResult
) -> Optional[str]:
    """Selects and enqueues one tick. Returns an outcome that ends it early (yielded, backlog) or None."""
    with database.get_background_db() as session:
        session.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        if session.execute(_LIVE_WORK, {"lane": queue.LANE_NOTIFICATION}).first() is not None:
            return OUTCOME_YIELDED
        params = {"statuses": list(statuses), "recheck_before": recheck_before}
        for resource in resources:
            eligible = session.execute(text("SELECT count(*) " + _eligible_sql(resource)), params).scalar() or 0
            result.resources[resource] = ResourceTick(eligible=eligible, batch=batch_size(eligible))
        wanted = sum(tick.batch for tick in result.resources.values())
        if session.execute(_SWEEP_BACKLOG, {"lane": queue.LANE_SWEEP}).scalar() >= BACKLOG_TICKS * wanted > 0:
            return OUTCOME_BACKLOG
        entries: List[queue.EnqueueEntry] = []
        for resource, tick in result.resources.items():
            if not tick.batch:
                continue
            ids = (
                session.execute(
                    text(
                        f"SELECT i.item_id {_eligible_sql(resource)} {_NOT_QUEUED} "
                        "ORDER BY s.last_checked_at ASC NULLS FIRST, i.item_id LIMIT :k"
                    ),
                    {**params, "k": tick.batch},
                )
                .scalars()
                .all()
            )
            tick.selected = len(ids)
            entries += [queue.EnqueueEntry(ITEM_KIND, i, queue.LANE_SWEEP, resources=(resource,)) for i in ids]
        queue.enqueue(entries, session=session)
        result.enqueued = len(entries)
    return None


def _record(result: SweepResult, resources: Sequence[str], started: datetime, finished: datetime) -> None:
    with database.get_background_db() as session:
        session.add(
            MlPubJobRun(
                job=JOB,
                scope=",".join(resources),
                started_at=started,
                finished_at=finished,
                outcome=result.outcome,
                counts=result.counts(),
                last_error=result.error[:1000] if result.error else None,
            )
        )


def run_sweep(
    *,
    statuses: Sequence[str],
    bundle_resources: Sequence[str],
    recheck_days: int,
    now: Callable[[], datetime] = _utcnow,
) -> SweepResult:
    """One tick. Never raises: a failure is in `result.error` and in the run record."""
    result = SweepResult()
    started = now()
    resources = [name for name in SWEEP_RESOURCES if name in bundle_resources]
    try:
        if not resources:
            result.outcome = OUTCOME_NO_RESOURCES
        else:
            early = _tick(statuses, resources, started - timedelta(days=recheck_days), result)
            result.outcome = early or OUTCOME_SUCCESS
    except Exception as exc:  # noqa: BLE001 -- the next tick retries
        logger.exception("sweep tick failed")
        result.outcome, result.error = OUTCOME_FAILED, f"internal_error: {type(exc).__name__}: {exc}"[:300]
    try:
        _record(result, resources, started, now())
    except Exception:  # noqa: BLE001 -- observability must never fail a tick
        logger.exception("could not record the sweep tick")
    return result
