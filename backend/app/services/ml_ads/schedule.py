"""What one worker run does, and in which order (ADS-5 backfill, ADS-6 daily refresh, D3, D4).

The unit of work is one `(advertiser, day)`. Everything a run needs to continue lives in the ledger
(`status`, `groups_offset`, the groups' drill status), so a run can be cut off anywhere: the caller's
`worker_job_state.detail` only says whether the last run finished and on which day it refreshed.

Work order of a run:

1. Once per local day, after the 10:30 slot (`refreshed_for != today`): D-1..D-3 and the mismatches that
   still have laps are marked `refetch`; closed days older than D-14 become final.
2. Resume days left `fetching` or `refetch`, oldest day first.
3. Fetch the days of the retention window that have no ledger row, oldest first (they expire first).
4. Verify D-4..D-14 with one summary call each, once per local day; a day whose figures moved is reopened
   and picked up by step 2.

A rate limit or a missing token ends the run. A day that failed is skipped for the rest of the run, so one
poison day never blocks the others, and the run reports itself incomplete so it is retried. Days ML no
longer retains are marked `unavailable` by the day pipeline itself and are never picked again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Optional

from app.core.config import settings
from app.services.ml_ads import ingestion, store
from app.services.ml_ads.ingestion import LOCAL_TZ, SessionFactory

REFRESH_AFTER = time(10, 30)  # ML refreshes the previous day at 10:00 GMT-3
RECENT_DAYS = 3  # D-1..D-3 are re-ingested every daily run
VERIFY_DAYS = 14  # D-4..D-14 are verified; older closed days are final
MISMATCH_LAPS = 3

_VERIFY = "verify"
_FETCH = "fetch"
# Outcomes that say nothing about the next unit: stop the run. `blocked` also finishes it (nothing to retry soon).
_STOPS = (ingestion.RATE_LIMITED, ingestion.BLOCKED, ingestion.DEADLINE_HIT)


@dataclass
class TickResult:
    steps: list[ingestion.StepResult] = field(default_factory=list)
    calls: int = 0
    stopped: Optional[str] = None
    complete: bool = True
    refreshed_for: Optional[date] = None

    def as_detail(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "stopped": self.stopped,
            "calls": self.calls,
            "refreshed_for": self.refreshed_for.isoformat() if self.refreshed_for else None,
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
    refreshed_for: Optional[date],
) -> TickResult:
    local_now = now().astimezone(LOCAL_TZ)
    today = local_now.date()
    result = TickResult(refreshed_for=refreshed_for)

    advertisers, outcome, result.calls = ingestion.list_advertisers(client, deadline=deadline, now=now)
    if outcome is not None:
        return _stopped(result, outcome)

    with session_factory() as db:
        store.finalize_old(db, before=today - timedelta(days=VERIFY_DAYS))
        if refreshed_for != today and local_now.time() >= REFRESH_AFTER:
            store.reopen_for_daily_run(db, today=today, recent_days=RECENT_DAYS, max_laps=MISMATCH_LAPS)
            result.refreshed_for = today

    skipped: set[tuple[int, date]] = set()
    while unit := _next_unit(session_factory, advertisers, today, skipped):
        kind, *key = unit
        run = ingestion.verify_ads_day if kind == _VERIFY else ingestion.run_ads_step
        step = run(session_factory, client, *key, now=now, deadline=deadline)
        result.steps.append(step)
        result.calls += step.calls
        if step.outcome in _STOPS:
            return _stopped(result, step.outcome)
        if step.outcome in (ingestion.ERROR, ingestion.ATTEMPTS_EXHAUSTED):
            skipped.add((step.advertiser_id, step.day))
            # A day out of attempts is retried tomorrow; one that just failed deserves the next run.
            result.complete = result.complete and step.outcome == ingestion.ATTEMPTS_EXHAUSTED
    return result


def _stopped(result: TickResult, outcome: str) -> TickResult:
    result.stopped = outcome
    result.complete = outcome == ingestion.BLOCKED  # a setup problem does not get better by retrying in a minute
    return result


def _next_unit(
    session_factory: SessionFactory, advertisers: list[int], today: date, skipped: set[tuple[int, date]]
) -> Optional[tuple[str, int, date]]:
    first = today - timedelta(days=settings.ML_ADS_RETENTION_DAYS)
    since = datetime.combine(today, time.min, tzinfo=LOCAL_TZ)
    with session_factory() as db:
        for unit in store.open_units(db):
            # A day of an advertiser ML no longer lists would fail on every run.
            if unit[0] in advertisers and unit not in skipped:
                return (_FETCH, *unit)
        have = store.ledgered(db, first, today - timedelta(days=1))
        due = store.unverified(db, today=today, newest_ago=RECENT_DAYS + 1, oldest_ago=VERIFY_DAYS, since=since)
    window = (first + timedelta(days=n) for n in range((today - first).days))
    missing = ((a, day) for day in window for a in advertisers if (a, day) not in have)
    if unit := next((unit for unit in missing if unit not in skipped), None):
        return (_FETCH, *unit)
    return next(((_VERIFY, *unit) for unit in due if unit[0] in advertisers and unit not in skipped), None)
