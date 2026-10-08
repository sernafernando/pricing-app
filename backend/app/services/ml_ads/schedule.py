"""What one worker run does, and in which order (ADS-5 backfill, D3, D4).

The unit of work is one `(advertiser, day)`. Everything a run needs to continue lives in the ledger
(`status`, `groups_offset`, the groups' drill status), so a run can be cut off anywhere: the caller's
`worker_job_state.detail` only says whether the last run finished.

Work order of a run:

1. Resume days left `fetching` or `refetch`, oldest day first.
2. Fetch the days of the retention window that have no ledger row, oldest first (they expire first).

A rate limit or a missing token ends the run. A day that failed is skipped for the rest of the run, so one
poison day never blocks the others, and the run reports itself incomplete so it is retried. Days ML no
longer retains are marked `unavailable` by the day pipeline itself and are never picked again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

from app.core.config import settings
from app.services.ml_ads import ingestion, store
from app.services.ml_ads.ingestion import LOCAL_TZ, SessionFactory

# Outcomes that say nothing about the next unit: stop the run. `blocked` also finishes it (nothing to retry soon).
_STOPS = (ingestion.RATE_LIMITED, ingestion.BLOCKED, ingestion.DEADLINE_HIT)


@dataclass
class TickResult:
    steps: list[ingestion.StepResult] = field(default_factory=list)
    calls: int = 0
    stopped: Optional[str] = None
    complete: bool = True

    def as_detail(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "stopped": self.stopped,
            "calls": self.calls,
            "steps": [
                {"advertiser_id": s.advertiser_id, "day": s.day.isoformat(), "outcome": s.outcome} for s in self.steps
            ],
        }


def run_tick(
    session_factory: SessionFactory,
    client: Any,
    *,
    now: Callable[[], datetime],
    deadline: Optional[datetime],
) -> TickResult:
    today = now().astimezone(LOCAL_TZ).date()
    result = TickResult()

    advertisers, outcome = ingestion.list_advertisers(client, deadline=deadline, now=now)
    result.calls += 0 if outcome in (ingestion.DEADLINE_HIT, ingestion.BLOCKED) else 1
    if outcome is not None:
        return _stopped(result, outcome)

    skipped: set[tuple[int, date]] = set()
    while unit := _next_day(session_factory, advertisers, today, skipped):
        step = ingestion.run_ads_step(session_factory, client, *unit, now=now, deadline=deadline)
        result.steps.append(step)
        result.calls += step.calls
        if step.outcome in _STOPS:
            return _stopped(result, step.outcome)
        if step.outcome in (ingestion.ERROR, ingestion.ATTEMPTS_EXHAUSTED):
            skipped.add(unit)
            # A day out of attempts is retried tomorrow; one that just failed deserves the next run.
            result.complete = result.complete and step.outcome == ingestion.ATTEMPTS_EXHAUSTED
    return result


def _stopped(result: TickResult, outcome: str) -> TickResult:
    result.stopped = outcome
    result.complete = outcome == ingestion.BLOCKED  # a setup problem does not get better by retrying in a minute
    return result


def _next_day(
    session_factory: SessionFactory, advertisers: list[int], today: date, skipped: set[tuple[int, date]]
) -> Optional[tuple[int, date]]:
    first = today - timedelta(days=settings.ML_ADS_RETENTION_DAYS)
    with session_factory() as db:
        for unit in store.open_units(db):
            if unit not in skipped:
                return unit
        have = store.ledgered(db, first, today - timedelta(days=1))
    window = (first + timedelta(days=n) for n in range((today - first).days))
    missing = ((a, day) for day in window for a in advertisers if (a, day) not in have)
    return next((unit for unit in missing if unit not in skipped), None)
