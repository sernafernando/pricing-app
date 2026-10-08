"""Ads day ingestion: one (advertiser, day) per `run_ads_step` (ADS-1, ADS-2, ADS-4).

Per day: page `ad_groups/search` (pages of 200), drill `/ads` (pages of 50) only for the groups that
spent, read `campaigns/search` `metrics_summary` for ML's own total, then close the ledger when the
groups add up to that total. Every request is followed by its own short transaction, so no DB session
is open while a request is in flight.

`run_ads_step` always (re)fetches the day it is given; choosing WHICH day (backfill order, refresh
policy) is the caller's job.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Mapping

from sqlalchemy.orm import Session

from app.services.ml_ads import endpoints, mapper, store

SessionFactory = Callable[[], AbstractContextManager[Session]]

CENT = Decimal("0.01")

# Outcomes of a step; they are also the ledger status the step leaves behind.
CLOSED = "closed"
MISMATCH = "mismatch"


class AdsRequestError(RuntimeError):
    """A request got no usable answer. The day stays `fetching`; nothing is recorded about the failure."""


@dataclass(frozen=True)
class StepResult:
    outcome: str
    status: str  # ledger status after the step


def _drill_status(sums: store.DrillSums) -> str:
    """ADS-2(b): the ads of a group must add up to ML's group cost, a cent of rounding per ad."""
    return "done" if abs(sums.group_cost - sums.items_cost) <= CENT * max(sums.items, 1) else "mismatch"


def _day_closes(check: store.DayCheck, summary: mapper.DaySummary) -> bool:
    """ADS-4: every group drilled and exact, and the groups add up to ML's day total (a cent per group)."""
    if check.pending or check.drill_mismatches:
        return False
    return abs(check.group_cost - summary.cost) <= CENT * max(check.groups, 1)


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
) -> StepResult:
    return _DayRun(session_factory, client, advertiser_id, day, now).execute()


class _DayRun:
    def __init__(
        self, session_factory: SessionFactory, client: Any, advertiser_id: int, day: date, now: Callable[[], datetime]
    ) -> None:
        self.session_factory = session_factory
        self.client = client
        self.advertiser_id = advertiser_id
        self.day = day
        self.now = now
        self.fetch_started_at: datetime

    def execute(self) -> StepResult:
        with self.session_factory() as db:
            self.fetch_started_at = store.start_fetch(db, self.advertiser_id, self.day, now=self.now()).fetch_started_at
        self._read_groups()
        self._drill_pending_groups()
        return self._close(self._read_summary())

    def _call(self, request: endpoints.AdsRequest) -> Mapping[str, Any]:
        response = self.client.get(request.family, request.path, request.params, headers=request.headers)
        if 200 <= response.status < 300 and response.error is None and isinstance(response.body, Mapping):
            return response.body
        problem = f"HTTP {response.status}" if response.status else f"transport error: {response.error}"
        raise AdsRequestError(f"{request.path}: {problem}")

    def _read_groups(self) -> None:
        offset = 0
        while True:
            body = self._call(endpoints.ad_groups_request(self.advertiser_id, self.day, offset=offset))
            facts = mapper.map_groups_page(self.advertiser_id, self.day, body)
            offset += endpoints.GROUPS_PAGE_SIZE
            with self.session_factory() as db:
                store.upsert_groups(db, facts, fetch_started_at=self.fetch_started_at, now=self.now())
            if _is_last_page(body, offset):
                return

    def _drill_pending_groups(self) -> None:
        with self.session_factory() as db:
            pending = store.pending_groups(db, self.advertiser_id, self.day)
        for group_id, _ in pending:
            self._drill(group_id)

    def _drill(self, group_id: int) -> None:
        offset = 0
        while True:
            body = self._call(endpoints.group_ads_request(group_id, self.day, offset=offset))
            items = mapper.map_ads_page(self.advertiser_id, group_id, self.day, body)
            offset += endpoints.ADS_PAGE_SIZE
            last = _is_last_page(body, offset)
            with self.session_factory() as db:
                store.upsert_items(db, items, now=self.now())
                if last:
                    sums = store.drill_sums(
                        db, self.advertiser_id, group_id, self.day, fetch_started_at=self.fetch_started_at
                    )
                    store.set_drill(
                        db, self.advertiser_id, group_id, self.day, status=_drill_status(sums), ads_offset=offset
                    )
            if last:
                return

    def _read_summary(self) -> mapper.DaySummary:
        summary = mapper.parse_summary(self._call(endpoints.campaigns_summary_request(self.advertiser_id, self.day)))
        if summary is None:
            raise AdsRequestError("campaigns/search without metrics_summary")
        return summary

    def _close(self, summary: mapper.DaySummary) -> StepResult:
        with self.session_factory() as db:
            store.delete_stale(db, self.advertiser_id, self.day, fetch_started_at=self.fetch_started_at)
            status = CLOSED if _day_closes(store.day_check(db, self.advertiser_id, self.day), summary) else MISMATCH
            store.finish_day(db, self.advertiser_id, self.day, status=status, summary=summary, now=self.now())
        return StepResult(status, status)
