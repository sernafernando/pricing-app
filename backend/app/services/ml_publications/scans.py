"""Scan engine of the ML publications store: backfill, rescans, missing-from-scan (design D17).

One LAP walks every configured status with `GET /users/{seller}/items/search?search_type=scan`
and the returned `scroll_id`. A lap spans many handler runs (each run is bounded by the worker
deadline) and survives restarts: all progress lives in `ml_pub_scan_state`, one row per status plus
one lap row (`LAP_ROW`) holding the mode and the lap start.

Modes
    full    backfill: every enumerated item is enqueued in the backfill lane. Used on request
            (`scan.next_mode = full`) and when the store is empty.
    rescan  every enumerated item is compared with its stored state and enqueued in the reconcile
            lane only when it is missing, gone, older than the staleness threshold, or its status
            differs. The comparison goes through `SCAN_TO_BODY_STATUS`: scan statuses and item body
            statuses are not the same vocabulary (a `pending` scan returns items whose body status
            is `inactive`).

When every status is terminal the lap ends with the missing-from-scan step: a stored item that no
scan returned during the lap gets a direct refresh (ML then answers 200 or 404 and the store records
it). Nothing is ever deleted.

Pages are processed in ONE short transaction (queue upserts, the narrow `last_scan_seen_at` update
and the progress row move together), so a crash re-reads at most the page in flight; re-enqueueing
is harmless because the queue dedupes.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import database
from app.models.ml_publications import MlItem, MlPubJobRun, MlPubScanState
from app.services.ml_publications import queue
from app.services.ml_publications.ml_http import OUTCOME_NO_TOKEN, OUTCOME_NOT_CONFIGURED, MlResponse
from app.services.ml_publications.pacing import DEADLINE
from app.services.ml_publications.resources import CORE_RESOURCE

logger = logging.getLogger(__name__)

MODE_FULL = "full"
MODE_RESCAN = "rescan"

ENDPOINT_FAMILY = "items_search_scan"
ITEM_KIND = "item"
LAP_ROW = "_lap"
JOB = "scan"

SCAN_LIMIT = 100
# A scroll_id lives about five minutes; an expired one restarts the status, at most this many times.
MAX_RESTARTS = 3
# Pages beyond the ceil(total / limit) that the total announced before a scroll counts as runaway.
OVERRUN_SLACK_PAGES = 5
UNSEEN_BATCH = 500

ERROR_MALFORMED = "malformed_scan_response"
ERROR_INVALID_SCROLL = "invalid.scroll.id"
STOP_DISABLED = "disabled"
STOP_DEADLINE = "deadline"
STOP_RATE_LIMITED = "rate_limited"

# Every status a scan can be asked for, and the body statuses each one returns. Only `pending` differs
# (captured 2026-10-06: the `pending` scan returns items whose body `status` is `inactive`).
ALL_SCAN_STATUSES = ("active", "paused", "closed", "under_review", "inactive", "pending")
SCAN_TO_BODY_STATUS: Mapping[str, FrozenSet[str]] = {"pending": frozenset({"inactive"})}


def body_statuses(scan_status: str) -> FrozenSet[str]:
    """The item body statuses a scan of `scan_status` returns."""
    return SCAN_TO_BODY_STATUS.get(scan_status, frozenset({scan_status}))


def covered_body_statuses(completed_scan_statuses: Iterable[str]) -> FrozenSet[str]:
    """Body statuses whose items a lap saw in full: every scan that can return the status completed."""
    completed = set(completed_scan_statuses)
    covered = set()
    for body_status in {b for s in ALL_SCAN_STATUSES for b in body_statuses(s)}:
        producers = [s for s in ALL_SCAN_STATUSES if body_status in body_statuses(s)]
        if all(p in completed for p in producers):
            covered.add(body_status)
    return frozenset(covered)


@dataclass(frozen=True)
class StoredItem:
    status: Optional[str]
    last_checked_at: Optional[datetime]
    gone_at: Optional[datetime]


def lane_for(
    mode: str, scan_status: str, stored: Optional[StoredItem], *, now: datetime, stale_days: int
) -> Optional[int]:
    """The queue lane an enumerated item goes to, or None when it needs no refresh."""
    if mode == MODE_FULL:
        return queue.LANE_BACKFILL
    if stored is None or stored.gone_at is not None:
        return queue.LANE_RECONCILE
    if stored.last_checked_at is None or stored.last_checked_at < now - timedelta(days=stale_days):
        return queue.LANE_RECONCILE
    if stored.status not in body_statuses(scan_status):
        return queue.LANE_RECONCILE
    return None


class MalformedScanPage(ValueError):
    pass


@dataclass(frozen=True)
class ScanPage:
    ids: List[str]
    scroll_id: str
    total: int


def parse_page(body: Any) -> ScanPage:
    """A scan answer: `results` (item ids), `paging.total`, `scroll_id` ("" when there is none)."""
    if not isinstance(body, dict):
        raise MalformedScanPage("body is not an object")
    results, paging, scroll_id = body.get("results"), body.get("paging"), body.get("scroll_id")
    if not isinstance(results, list) or not all(isinstance(i, str) and i for i in results):
        raise MalformedScanPage("results is not a list of item ids")
    if (
        not isinstance(paging, dict)
        or isinstance(paging.get("total"), bool)
        or not isinstance(paging.get("total"), int)
    ):
        raise MalformedScanPage("paging.total is not an integer")
    if scroll_id is not None and not isinstance(scroll_id, str):
        raise MalformedScanPage("scroll_id is not a string")
    return ScanPage(ids=list(dict.fromkeys(results)), scroll_id=scroll_id or "", total=paging["total"])


@dataclass
class ScanResult:
    """What one run did. `complete` is True only when the lap ended (missing-from-scan step included)."""

    mode: Optional[str] = None
    complete: bool = False
    stopped: Optional[str] = None
    error: Optional[str] = None
    pages: int = 0
    enumerated: int = 0
    enqueued: int = 0
    missing_enqueued: int = 0
    failed_statuses: List[str] = field(default_factory=list)
    unsupported_statuses: List[str] = field(default_factory=list)
    statuses: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def as_detail(self) -> Dict[str, Any]:
        detail: Dict[str, Any] = {
            "complete": self.complete,
            "mode": self.mode,
            "pages": self.pages,
            "enumerated": self.enumerated,
            "enqueued": self.enqueued,
            "missing_enqueued": self.missing_enqueued,
            "failed_statuses": self.failed_statuses,
            "unsupported_statuses": self.unsupported_statuses,
            "statuses": self.statuses,
        }
        if self.stopped:
            detail["stopped"] = self.stopped
        if self.error:
            detail["error"] = self.error
        return detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _snapshot(row: MlPubScanState) -> Dict[str, Any]:
    return {
        "pages": row.pages or 0,
        "enumerated": row.enumerated or 0,
        "enqueued": row.enqueued or 0,
        "restarts": row.restarts or 0,
        "unsupported": bool(row.unsupported),
        "completed": row.completed_at is not None,
        "error": row.last_error,
    }


def _is_failed(row: MlPubScanState) -> bool:
    return row.completed_at is not None and bool(row.last_error) and not row.unsupported


def _reset(row: MlPubScanState, *, mode: Optional[str], lap_started_at: datetime) -> None:
    row.mode = mode
    row.scroll_id = None
    row.scroll_started_at = None
    row.pages = 0
    row.enumerated = 0
    row.enqueued = 0
    row.restarts = 0
    row.unsupported = False
    row.lap_started_at = lap_started_at
    row.started_at = None
    row.completed_at = None
    row.last_error = None


@dataclass(frozen=True)
class _Lap:
    mode: str
    started_at: datetime


# --- lap lifecycle --------------------------------------------------------------------------


def _close_dangling_run(session: Session, now: datetime, outcome: str) -> None:
    for run in session.query(MlPubJobRun).filter(MlPubJobRun.job == JOB, MlPubJobRun.finished_at.is_(None)).all():
        run.finished_at = now
        run.outcome = outcome


def _open_lap(statuses: Sequence[str], requested_mode: Optional[str], now: datetime) -> _Lap:
    """The lap this run works on: the open one, or a new one (mode: requested full, else full on an
    empty store, else rescan). A full request restarts an open rescan lap; a lap already full is kept."""
    with database.get_background_db() as session:
        lap_row = session.get(MlPubScanState, LAP_ROW)
        is_open = lap_row is not None and lap_row.completed_at is None and lap_row.lap_started_at is not None
        wants_full = requested_mode == MODE_FULL
        new_lap = not is_open or (wants_full and lap_row.mode != MODE_FULL)
        if not new_lap:
            lap = _Lap(mode=lap_row.mode, started_at=lap_row.lap_started_at)
        else:
            store_empty = session.execute(select(MlItem.item_id).limit(1)).first() is None
            mode = MODE_FULL if wants_full or store_empty else MODE_RESCAN
            lap = _Lap(mode=mode, started_at=now)
            if lap_row is None:
                lap_row = MlPubScanState(status=LAP_ROW)
                session.add(lap_row)
            _reset(lap_row, mode=mode, lap_started_at=now)
            lap_row.started_at = now
            _close_dangling_run(session, now, "superseded")
            session.add(MlPubJobRun(job=JOB, scope=mode, started_at=now, counts={}))
        for status in statuses:
            row = session.get(MlPubScanState, status)
            if row is None:
                row = MlPubScanState(status=status)
                session.add(row)
                _reset(row, mode=lap.mode, lap_started_at=lap.started_at)
            elif new_lap or row.lap_started_at != lap.started_at:
                _reset(row, mode=lap.mode, lap_started_at=lap.started_at)
        return lap


def _states(statuses: Sequence[str]) -> Dict[str, MlPubScanState]:
    with database.get_background_db() as session:
        rows = {s: session.get(MlPubScanState, s) for s in statuses}
        session.expunge_all()
    return rows  # type: ignore[return-value]


def _summarize(result: ScanResult, statuses: Sequence[str]) -> None:
    rows = _states(statuses)
    result.statuses = {s: _snapshot(r) for s, r in rows.items() if r is not None}
    result.failed_statuses = [s for s, r in rows.items() if r is not None and _is_failed(r)]
    result.unsupported_statuses = [s for s, r in rows.items() if r is not None and r.unsupported]


def _close_lap(statuses: Sequence[str], lap: _Lap, result: ScanResult, now: datetime) -> None:
    _summarize(result, statuses)
    counts = {
        "mode": lap.mode,
        "enumerated": sum(s["enumerated"] for s in result.statuses.values()),
        "enqueued": sum(s["enqueued"] for s in result.statuses.values()) + result.missing_enqueued,
        "missing_enqueued": result.missing_enqueued,
        "restarts": sum(s["restarts"] for s in result.statuses.values()),
        "statuses": result.statuses,
    }
    failed = ", ".join(f"{s}: {result.statuses[s]['error']}" for s in result.failed_statuses)
    with database.get_background_db() as session:
        lap_row = session.get(MlPubScanState, LAP_ROW)
        lap_row.completed_at = now
        lap_row.enumerated = counts["enumerated"]
        lap_row.enqueued = counts["enqueued"]
        lap_row.restarts = counts["restarts"]
        lap_row.last_error = failed or None
        run = (
            session.query(MlPubJobRun)
            .filter(MlPubJobRun.job == JOB, MlPubJobRun.finished_at.is_(None))
            .order_by(MlPubJobRun.started_at.desc())
            .first()
        )
        if run is not None:
            run.finished_at = now
            run.outcome = "failed" if failed else "success"
            run.counts = counts
            run.last_error = failed or None


def record_failure(error: str, now: Optional[datetime] = None) -> None:
    """Note an unexpected failure on the open lap record, or leave a closed `error` record when there is none."""
    moment = now or _utcnow()
    with database.get_background_db() as session:
        run = (
            session.query(MlPubJobRun)
            .filter(MlPubJobRun.job == JOB, MlPubJobRun.finished_at.is_(None))
            .order_by(MlPubJobRun.started_at.desc())
            .first()
        )
        if run is not None:
            run.last_error = error[:1000]
        else:
            session.add(
                MlPubJobRun(job=JOB, started_at=moment, finished_at=moment, outcome="error", last_error=error[:1000])
            )


# --- one status -----------------------------------------------------------------------------


def _store_state(status: str, **changes: Any) -> None:
    with database.get_background_db() as session:
        row = session.get(MlPubScanState, status)
        for key, value in changes.items():
            setattr(row, key, value)


def _stored_items(session: Session, ids: Sequence[str]) -> Dict[str, StoredItem]:
    rows = session.execute(
        select(MlItem.item_id, MlItem.status, MlItem.last_checked_at, MlItem.gone_at).where(MlItem.item_id.in_(ids))
    ).all()
    return {r[0]: StoredItem(status=r[1], last_checked_at=r[2], gone_at=r[3]) for r in rows}


def _apply_page(
    status: str, page: ScanPage, lap: _Lap, *, now: datetime, stale_days: int, finished: bool, result: ScanResult
) -> None:
    """One transaction: enqueue what the mode asks for, mark the stored items seen, move the progress."""
    with database.get_background_db() as session:
        row = session.get(MlPubScanState, status)
        entries: List[queue.EnqueueEntry] = []
        if page.ids:
            stored = _stored_items(session, page.ids)
            for item_id in page.ids:
                lane = lane_for(lap.mode, status, stored.get(item_id), now=now, stale_days=stale_days)
                if lane is not None:
                    entries.append(queue.EnqueueEntry(ITEM_KIND, item_id, lane))
            queue.enqueue(entries, session=session)
            if stored:
                session.execute(update(MlItem).where(MlItem.item_id.in_(list(stored))).values(last_scan_seen_at=now))
        if row.started_at is None:
            row.started_at = now
        if not row.pages:
            row.scroll_started_at = now
        row.pages = (row.pages or 0) + 1
        row.enumerated = (row.enumerated or 0) + len(page.ids)
        row.enqueued = (row.enqueued or 0) + len(entries)
        row.last_error = None  # a page went through: an earlier transient error no longer applies
        if finished:
            row.scroll_id = None
            row.completed_at = now
        else:
            row.scroll_id = page.scroll_id
        result.pages += 1
        result.enumerated += len(page.ids)
        result.enqueued += len(entries)


def _expected_pages(total: int) -> int:
    return math.ceil(max(total, 1) / SCAN_LIMIT)


def _scan_status(
    client: Any,
    status: str,
    lap: _Lap,
    *,
    seller_id: str,
    stale_days: int,
    keep_going: Callable[[], bool],
    deadline: datetime,
    now: Callable[[], datetime],
    result: ScanResult,
) -> bool:
    """Walks `status` until it is terminal. Returns True when the RUN must stop (reason in `result`)."""
    while True:
        if not keep_going():
            result.stopped = STOP_DISABLED
            return True
        if _utcnow() >= deadline:
            result.stopped = STOP_DEADLINE
            return True
        state = _states([status])[status]
        scroll_id = state.scroll_id
        params: Dict[str, Any] = {"search_type": "scan", "status": status, "limit": SCAN_LIMIT}
        if scroll_id:
            params["scroll_id"] = scroll_id
        response: MlResponse = client.get(
            ENDPOINT_FAMILY, f"/users/{seller_id}/items/search", params, deadline=deadline
        )
        if response.error == DEADLINE:
            result.stopped = STOP_DEADLINE
            return True
        if response.error in (OUTCOME_NOT_CONFIGURED, OUTCOME_NO_TOKEN):
            result.error = str(response.error)
            return True
        if response.status == 401:
            result.error = "unauthorized"
            return True
        if response.status == 429:
            result.stopped = STOP_RATE_LIMITED
            return True
        if response.status == 400:
            if _handle_rejection(status, state, response, now()):
                continue  # the scroll expired: ask again from the first page
            return False  # unsupported or failed: the status is terminal, the lap moves on
        if response.error or not 200 <= response.status < 300:
            result.error = response.error or f"http_{response.status}"
            _store_state(status, last_error=result.error)
            return True
        try:
            page = parse_page(response.body)
        except MalformedScanPage as exc:
            logger.warning("malformed scan page for %s: %s", status, exc)
            result.error = ERROR_MALFORMED
            _store_state(status, last_error=f"{ERROR_MALFORMED}: {exc}"[:300])
            return True
        overrun = (state.pages or 0) + 1 > _expected_pages(page.total) + OVERRUN_SLACK_PAGES
        finished = not page.ids or not page.scroll_id
        _apply_page(status, page, lap, now=now(), stale_days=stale_days, finished=finished or overrun, result=result)
        if overrun and not finished:
            _store_state(status, last_error=f"scan_overrun: more than {_expected_pages(page.total)} pages announced")
        if finished or overrun:
            return False


def _handle_rejection(status: str, state: MlPubScanState, response: MlResponse, now: datetime) -> bool:
    """A 400. Returns True when the status must be asked again (scroll restarted)."""
    body = response.body if isinstance(response.body, dict) else {}
    if state.scroll_id and body.get("error") == ERROR_INVALID_SCROLL:
        restarts = state.restarts or 0
        if restarts >= MAX_RESTARTS:
            _store_state(
                status,
                scroll_id=None,
                completed_at=now,
                last_error=f"scroll expired {restarts} times: restarts exhausted",
            )
            return False
        # the counts describe the scroll in progress; `restarts` keeps the history
        _store_state(
            status, scroll_id=None, scroll_started_at=None, pages=0, enumerated=0, enqueued=0, restarts=restarts + 1
        )
        return True
    if state.scroll_id:  # a 400 on a scroll that is not the documented expiry: not a status problem
        _store_state(
            status, scroll_id=None, completed_at=now, last_error=f"unexpected 400 on scroll: {body.get('error')}"
        )
        return False
    _store_state(
        status,
        unsupported=True,
        completed_at=now,
        last_error=f"unsupported: HTTP 400 {body.get('error') or ''}".strip(),
    )
    return False


# --- missing from scan ------------------------------------------------------------------------


def _enqueue_unseen(statuses: Sequence[str], lap: _Lap, *, now: datetime, stale_days: int) -> int:
    """Stored, non-gone items of fully covered statuses that no scan returned during the lap.

    A `closed` item is refreshed only once stale: closed items drop out of the scans while ML keeps
    answering 200 for them, so refreshing them on every lap would never end."""
    stale_before = now - timedelta(days=stale_days)
    rows = _states(statuses)
    completed = [s for s, r in rows.items() if r is not None and r.completed_at is not None and not r.last_error]
    covered = sorted(covered_body_statuses(completed))
    if not covered:
        return 0
    total, after = 0, ""
    while True:
        with database.get_background_db() as session:
            ids = (
                session.execute(
                    select(MlItem.item_id)
                    .where(
                        MlItem.gone_at.is_(None),
                        MlItem.status.in_(covered),
                        (MlItem.last_scan_seen_at.is_(None)) | (MlItem.last_scan_seen_at < lap.started_at),
                        MlItem.item_id > after,
                        (MlItem.status != "closed")
                        | (MlItem.last_checked_at.is_(None))
                        | (MlItem.last_checked_at < stale_before),
                    )
                    .order_by(MlItem.item_id)
                    .limit(UNSEEN_BATCH)
                )
                .scalars()
                .all()
            )
            if not ids:
                return total
            queue.enqueue(
                [queue.EnqueueEntry(ITEM_KIND, i, queue.LANE_RECONCILE, resources=(CORE_RESOURCE,)) for i in ids],
                session=session,
            )
        total += len(ids)
        after = ids[-1]


# --- the run ----------------------------------------------------------------------------------


def run_scan(
    client: Any,
    *,
    seller_id: str,
    statuses: Sequence[str],
    requested_mode: Optional[str],
    stale_days: int,
    keep_going: Callable[[], bool],
    deadline: datetime,
    now: Callable[[], datetime] = _utcnow,
) -> ScanResult:
    """Advance the current lap as far as the deadline, the flag and ML allow."""
    ordered = list(dict.fromkeys(statuses))
    result = ScanResult()
    lap = _open_lap(ordered, requested_mode, now())
    result.mode = lap.mode
    for status in ordered:
        if _states([status])[status].completed_at is not None:
            continue
        stop = _scan_status(
            client,
            status,
            lap,
            seller_id=seller_id,
            stale_days=stale_days,
            keep_going=keep_going,
            deadline=deadline,
            now=now,
            result=result,
        )
        if stop:
            _summarize(result, ordered)
            return result
    result.missing_enqueued = _enqueue_unseen(ordered, lap, now=now(), stale_days=stale_days)
    _close_lap(ordered, lap, result, now())
    result.complete = True
    return result
