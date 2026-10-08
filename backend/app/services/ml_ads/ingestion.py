"""Ads day ingestion: one (advertiser, day) per `run_ads_step` (ADS-1..ADS-5, D2-D4).

Per day: page `ad_groups/search` (pages of 200), drill `/ads` (pages of 50) only for the groups that
spent, read `campaigns/search` `metrics_summary` for ML's own total, then verify and close. The ledger
row and each group's drill status are the cursor, so every request is followed by its own short
transaction and no DB session is open while a request is in flight (a stopped run loses at most the
page in flight).

`run_ads_step` always (re)fetches the day it is given; choosing WHICH day (backfill order, refresh
policy) is the caller's job (PR 1c).
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Mapping, NoReturn, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.ml_ads import endpoints, mapper, store
from app.services.ml_publications.pacing import DEADLINE
from app.services.ml_publications.ml_http import OUTCOME_NO_TOKEN, OUTCOME_NOT_CONFIGURED, MlResponse

SessionFactory = Callable[[], AbstractContextManager[Session]]

LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
MAX_ATTEMPTS_PER_DAY = 5
CENT = Decimal("0.01")

# Outcomes of a step.
CLOSED = "closed"
MISMATCH = "mismatch"
UNAVAILABLE = "unavailable"
RATE_LIMITED = "rate_limited"
BLOCKED = "blocked"
DEADLINE_HIT = "deadline"
ERROR = "error"
ATTEMPTS_EXHAUSTED = "attempts_exhausted"


@dataclass(frozen=True)
class StepResult:
    advertiser_id: int
    day: date
    outcome: str
    status: Optional[str]  # ledger status after the step
    calls: int


class _Stop(Exception):
    def __init__(self, outcome: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome


def _drill_status(sums: store.DrillSums) -> str:
    """D2: the ads of a group must add up to ML's group cost, a cent of rounding per ad."""
    return "done" if abs(sums.group_cost - sums.items_cost) <= CENT * max(sums.items, 1) else "mismatch"


def _day_closes(check: store.DayCheck, summary: mapper.DaySummary) -> bool:
    """D2: every group drilled and exact, and the groups add up to ML's day total (a cent per group)."""
    if check.pending or check.drill_mismatches:
        return False
    return abs(check.group_cost - summary.cost) <= CENT * max(check.groups, 1)


def _describe(response: MlResponse) -> str:
    return f"HTTP {response.status}" if response.status else f"transport error: {response.error}"


def _is_last_page(body: Mapping[str, Any], next_offset: int) -> bool:
    total = (body.get("paging") or {}).get("total")
    return total is None or next_offset >= int(total)


def run_ads_step(
    session_factory: SessionFactory,
    client: Any,
    advertiser_id: int,
    day: date,
    *,
    now: Callable[[], datetime],
    deadline: Optional[datetime] = None,
) -> StepResult:
    return _DayRun(session_factory, client, advertiser_id, day, now, deadline).execute()


class _DayRun:
    def __init__(
        self,
        session_factory: SessionFactory,
        client: Any,
        advertiser_id: int,
        day: date,
        now: Callable[[], datetime],
        deadline: Optional[datetime],
    ) -> None:
        self.session_factory = session_factory
        self.client = client
        self.advertiser_id = advertiser_id
        self.day = day
        self.now = now
        self.deadline = deadline
        self.calls = 0
        self.fetch_started_at: datetime
        self.groups_offset = 0

    # --- driver ---------------------------------------------------------------------------

    def execute(self) -> StepResult:
        try:
            self._open()
            self._read_groups()
            self._drill_pending_groups()
            return self._close(self._read_summary())
        except _Stop as stop:
            return self._result(stop.outcome)

    def _result(self, outcome: str) -> StepResult:
        with self.session_factory() as db:
            ledger = store.get_ledger(db, self.advertiser_id, self.day)
            status = ledger.status if ledger is not None else None
        return StepResult(self.advertiser_id, self.day, outcome, status, self.calls)

    @property
    def _today(self) -> date:
        return self.now().astimezone(LOCAL_TZ).date()

    def _open(self) -> None:
        with self.session_factory() as db:
            exhausted = store.attempts_exhausted(
                db, self.advertiser_id, self.day, today=self._today, limit=MAX_ATTEMPTS_PER_DAY
            )
            if not exhausted:
                ledger = store.start_fetch(db, self.advertiser_id, self.day, now=self.now())
                self.fetch_started_at = ledger.fetch_started_at
                self.groups_offset = ledger.groups_offset
        if exhausted:
            raise _Stop(ATTEMPTS_EXHAUSTED)

    # --- one request ----------------------------------------------------------------------

    def _call(self, request: endpoints.AdsRequest) -> Mapping[str, Any]:
        if self.deadline is not None and self.now() >= self.deadline:
            raise _Stop(DEADLINE_HIT)
        response = self.client.get(
            request.family, request.path, request.params, deadline=self.deadline, headers=request.headers
        )
        if response.error == DEADLINE:
            raise _Stop(DEADLINE_HIT)
        self.calls += 1
        if response.error in (OUTCOME_NOT_CONFIGURED, OUTCOME_NO_TOKEN) or response.status == 401:
            raise _Stop(BLOCKED)
        if response.status == 429:
            raise _Stop(RATE_LIMITED)
        if 200 <= response.status < 300 and response.error is None and isinstance(response.body, Mapping):
            return response.body
        self._fail(response)

    def _fail(self, response: MlResponse) -> NoReturn:
        """D4: a 4xx on a day past retention is terminal; anything else is one counted attempt."""
        terminal = 400 <= response.status < 500 and (self._today - self.day).days > settings.ML_ADS_RETENTION_DAYS
        with self.session_factory() as db:
            store.record_failure(db, self.advertiser_id, self.day, today=self._today, error=_describe(response))
            if terminal:
                store.finish_day(db, self.advertiser_id, self.day, status="unavailable", summary=None, now=self.now())
        # Raised after the transaction closes: the factory rolls back on an exception.
        raise _Stop(UNAVAILABLE if terminal else ERROR)

    # --- phases ---------------------------------------------------------------------------

    def _read_groups(self) -> None:
        offset = self.groups_offset
        while offset != store.GROUPS_DONE:
            body = self._call(endpoints.ad_groups_request(self.advertiser_id, self.day, offset=offset))
            facts = mapper.map_groups_page(self.advertiser_id, self.day, body)
            offset += endpoints.GROUPS_PAGE_SIZE
            if _is_last_page(body, offset):
                offset = store.GROUPS_DONE
            with self.session_factory() as db:
                store.upsert_groups(db, facts, fetch_started_at=self.fetch_started_at, now=self.now())
                store.set_groups_offset(db, self.advertiser_id, self.day, offset)

    def _drill_pending_groups(self) -> None:
        with self.session_factory() as db:
            pending = store.pending_groups(db, self.advertiser_id, self.day)
        for group_id, ads_offset in pending:
            self._drill(group_id, ads_offset)

    def _drill(self, group_id: int, offset: int) -> None:
        while True:
            body = self._call(endpoints.group_ads_request(group_id, self.day, offset=offset))
            items = mapper.map_ads_page(self.advertiser_id, group_id, self.day, body)
            offset += endpoints.ADS_PAGE_SIZE
            last = _is_last_page(body, offset)
            with self.session_factory() as db:
                store.upsert_items(db, items, now=self.now())
                status = "pending"
                if last:
                    # Rows of an earlier fetch only go when the day closes; they must not count here.
                    sums = store.drill_sums(
                        db, self.advertiser_id, group_id, self.day, fetch_started_at=self.fetch_started_at
                    )
                    status = _drill_status(sums)
                store.set_drill(db, self.advertiser_id, group_id, self.day, status=status, ads_offset=offset)
            if last:
                return

    def _read_summary(self) -> mapper.DaySummary:
        body = self._call(endpoints.campaigns_summary_request(self.advertiser_id, self.day))
        summary = mapper.parse_summary(body)
        if summary is None:
            with self.session_factory() as db:
                store.record_failure(
                    db,
                    self.advertiser_id,
                    self.day,
                    today=self._today,
                    error="campaigns/search without metrics_summary",
                )
            raise _Stop(ERROR)
        return summary

    def _close(self, summary: mapper.DaySummary) -> StepResult:
        with self.session_factory() as db:
            store.delete_stale(db, self.advertiser_id, self.day, fetch_started_at=self.fetch_started_at)
            status = CLOSED if _day_closes(store.day_check(db, self.advertiser_id, self.day), summary) else MISMATCH
            store.finish_day(db, self.advertiser_id, self.day, status=status, summary=summary, now=self.now())
        return StepResult(self.advertiser_id, self.day, status, status, self.calls)
