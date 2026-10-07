"""`/missed_feeds` recovery (design D17): notifications ML could not deliver, enqueued in the reconcile lane.

Per mapped intake topic the run pages `GET /missed_feeds?app_id&topic&site_id=MLA&limit&offset` until ML
answers `{messages: null}` (the captured end of the list, also what a page past the last offset returns). Only
`resource`, `topic`, `user_id` and `received` of a message are used: the delivery attempt (`request`,
`response`) is read past and never stored. The resource goes through the intake topic parser and the intake
classification (`intake.classify`), so a missed event and a delivered one produce the same queue entry.

A run records itself in `ml_pub_job_runs` (success, partial, failed). It also carries its own position
(`MissedFeedsResult.resume`) so the handler can continue a run that the worker deadline, a flag or a 429
interrupted. ML keeps missed feeds for 2 days: when the last successful run is older than
`GAP_HOURS`, the run records a coverage gap and requests a rescan, once per gap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set

from sqlalchemy import text

from app.core import database
from app.models.ml_publications import MlPubJobRun
from app.services.ml_publications import intake, queue, scans
from app.services.ml_publications.ml_http import OUTCOME_NO_TOKEN, OUTCOME_NOT_CONFIGURED, MlResponse
from app.services.ml_publications.pacing import DEADLINE

logger = logging.getLogger(__name__)

JOB = "missed_feeds"
ENDPOINT_FAMILY = "missed_feeds"
SITE_ID = "MLA"
# The capture used `limit=5`; ML's own ceiling is not in it, so the page stays small, and a short page never
# ends the list (the capture's `limit=5` page held 3 messages): only `{messages: null}` does.
PAGE_LIMIT = 20
# ML keeps missed feeds for 2 days: a longer silence than this can have lost events (design D17: 48 h).
GAP_HOURS = 48

ERROR_MALFORMED = "malformed_missed_feeds_response"
STOP_DISABLED = "disabled"
STOP_DEADLINE = "deadline"
STOP_RATE_LIMITED = "rate_limited"

OUTCOME_SUCCESS = "success"
OUTCOME_PARTIAL = "partial"
OUTCOME_FAILED = "failed"


@dataclass
class MissedFeedsResult:
    """What one run did. `complete` is True only when every mapped topic reached its end. `resume` is the
    position (topic, offset) to continue from when the run stopped early, else None."""

    complete: bool = False
    stopped: Optional[str] = None
    error: Optional[str] = None
    resume: Optional[Dict[str, Any]] = None
    gap: Optional[Dict[str, Any]] = None
    pages: int = 0
    messages: int = 0
    enqueued: int = 0
    satisfied: int = 0
    foreign: int = 0
    unparsed: int = 0
    duplicates: int = 0
    repeated_pages: int = 0
    requests: Dict[str, int] = field(default_factory=dict)

    @property
    def outcome(self) -> str:
        if self.error:
            return OUTCOME_FAILED
        return OUTCOME_SUCCESS if self.complete else OUTCOME_PARTIAL

    def counts(self) -> Dict[str, Any]:
        counts: Dict[str, Any] = {
            "pages": self.pages,
            "messages": self.messages,
            "enqueued": self.enqueued,
            "satisfied": self.satisfied,
            "foreign": self.foreign,
            "unparsed": self.unparsed,
            "duplicates": self.duplicates,
            "repeated_pages": self.repeated_pages,
            "requests": self.requests,
        }
        if self.gap:
            counts["coverage_gap"] = self.gap
        if self.stopped:
            counts["stopped"] = self.stopped
        if self.resume:
            counts["resume"] = self.resume
        return counts

    def as_detail(self) -> Dict[str, Any]:
        detail: Dict[str, Any] = {"complete": self.complete, "outcome": self.outcome, **self.counts()}
        if self.error:
            detail["error"] = self.error
        return detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_received(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# --- coverage gap -----------------------------------------------------------------------------

_LAST_SUCCESS = text(
    "SELECT finished_at FROM ml_pub_job_runs WHERE job = :job AND outcome = 'success' AND finished_at IS NOT NULL "
    "ORDER BY started_at DESC LIMIT 1"
)
_GAP_ALREADY_RECORDED = text(
    "SELECT 1 FROM ml_pub_job_runs "
    "WHERE job = :job AND started_at > :after AND counts -> 'coverage_gap' IS NOT NULL LIMIT 1"
)


def _detect_gap(now: datetime) -> Optional[Dict[str, Any]]:
    """The coverage gap this run must record, or None: no earlier success to compare with (first run), a
    success within `GAP_HOURS`, or a gap already recorded since that success (a retry of the same gap)."""
    with database.get_background_db() as session:
        last = session.execute(_LAST_SUCCESS, {"job": JOB}).scalar()
        if last is None or now - last <= timedelta(hours=GAP_HOURS):
            return None
        if session.execute(_GAP_ALREADY_RECORDED, {"job": JOB, "after": last}).first() is not None:
            return None
    return {
        "last_success_at": last.astimezone(timezone.utc).isoformat(),
        "hours": round((now - last).total_seconds() / 3600, 1),
    }


# --- one run ----------------------------------------------------------------------------------


def _request_counts(client: Any) -> Dict[str, int]:
    counters = getattr(client, "counters", None)
    return dict(counters.snapshot().get(ENDPOINT_FAMILY, {})) if counters is not None else {}


def _delta(after: Mapping[str, int], before: Mapping[str, int]) -> Dict[str, int]:
    return {k: v - before.get(k, 0) for k, v in after.items() if v - before.get(k, 0)}


def _page_keys(messages: Sequence[Any]) -> Set[str]:
    """What identifies the messages of a page: their `_id`, or their resource when a message has none."""
    keys: Set[str] = set()
    for message in messages:
        if isinstance(message, Mapping):
            key = message.get("_id") if isinstance(message.get("_id"), str) else message.get("resource")
            if isinstance(key, str) and key:
                keys.add(key)
    return keys


def _apply_page(
    mapping: intake.TopicMapping,
    messages: Sequence[Any],
    *,
    seller_id: str,
    seen: Set[str],
    now: datetime,
    result: MissedFeedsResult,
) -> None:
    """One transaction: classify the page through the intake rules and enqueue it in the reconcile lane."""
    rows: List[intake.NotificationRow] = []
    for message in messages:
        if not isinstance(message, Mapping):
            result.unparsed += 1
            continue
        resource = message.get("resource")
        resource = resource if isinstance(resource, str) else ""
        item_id = intake.parse_resource(mapping.topic, resource)
        if item_id is not None:
            if item_id in seen:
                result.duplicates += 1
                continue
            seen.add(item_id)
        user_id = message.get("user_id")
        rows.append(
            intake.NotificationRow(
                resource=resource,
                received_at=_parse_received(message.get("received")) or now,
                user_id=None if user_id is None else str(user_id),
            )
        )
    with database.get_background_db() as session:
        classified = intake.classify(session, mapping, rows, seller_id, lane=queue.LANE_RECONCILE)
        queue.enqueue(classified.entries, session=session)
    result.enqueued += len(classified.entries)
    result.satisfied += classified.satisfied
    result.foreign += classified.foreign
    result.unparsed += classified.unparsed


def _walk_topic(
    client: Any,
    mapping: intake.TopicMapping,
    offset: int,
    *,
    app_id: str,
    seller_id: str,
    keep_going: Callable[[], bool],
    deadline: datetime,
    now: Callable[[], datetime],
    result: MissedFeedsResult,
) -> bool:
    """Pages one topic to its end. Returns True when the RUN must stop (reason and position in `result`)."""
    seen: Set[str] = set()
    seen_ids: Set[str] = set()

    def stop(reason: Optional[str] = None, error: Optional[str] = None) -> bool:
        result.stopped, result.error = reason, error
        result.resume = {"topic": mapping.topic, "offset": offset}
        return True

    while True:
        if not keep_going():
            return stop(STOP_DISABLED)
        if _utcnow() >= deadline:
            return stop(STOP_DEADLINE)
        # the position of the page in flight: an unexpected error while applying it leaves the run here
        result.resume = {"topic": mapping.topic, "offset": offset}
        params = {"app_id": app_id, "topic": mapping.topic, "site_id": SITE_ID, "limit": PAGE_LIMIT, "offset": offset}
        response: MlResponse = client.get(ENDPOINT_FAMILY, "/missed_feeds", params, deadline=deadline)
        if response.error == DEADLINE:
            return stop(STOP_DEADLINE)
        if response.error in (OUTCOME_NOT_CONFIGURED, OUTCOME_NO_TOKEN):
            return stop(error=str(response.error))
        if response.status == 429:
            return stop(STOP_RATE_LIMITED)
        if response.error or not 200 <= response.status < 300:
            return stop(error=response.error or f"http_{response.status}")
        body = response.body
        if not isinstance(body, dict) or "messages" not in body:
            return stop(error=ERROR_MALFORMED)
        messages = body["messages"]
        if messages is None or messages == []:
            return False  # the captured end of the list
        if not isinstance(messages, list):
            return stop(error=ERROR_MALFORMED)
        ids = _page_keys(messages)
        if ids and ids <= seen_ids:  # ML answered a page this run already read: the list is not advancing
            result.repeated_pages += 1
            logger.warning("missed feeds topic %s repeats a page at offset %s; ending the topic", mapping.topic, offset)
            return False
        seen_ids |= ids
        _apply_page(mapping, messages, seller_id=seller_id, seen=seen, now=now(), result=result)
        result.pages += 1
        result.messages += len(messages)
        offset += PAGE_LIMIT


def _walk(
    client: Any,
    mappings: Sequence[intake.TopicMapping],
    resume: Optional[Mapping[str, Any]],
    *,
    app_id: str,
    seller_id: str,
    keep_going: Callable[[], bool],
    deadline: datetime,
    now: Callable[[], datetime],
    result: MissedFeedsResult,
) -> None:
    start_topic = resume.get("topic") if resume else None
    start_offset = resume.get("offset") if resume else 0
    skipping = start_topic in [m.topic for m in mappings]
    for mapping in mappings:
        if skipping and mapping.topic != start_topic:
            continue
        offset = start_offset if skipping and isinstance(start_offset, int) and start_offset >= 0 else 0
        skipping = False
        if _walk_topic(
            client,
            mapping,
            offset,
            app_id=app_id,
            seller_id=seller_id,
            keep_going=keep_going,
            deadline=deadline,
            now=now,
            result=result,
        ):
            return
    result.complete = True
    result.resume = None


def _record(
    result: MissedFeedsResult, mappings: Sequence[intake.TopicMapping], started: datetime, finished: datetime
) -> None:
    with database.get_background_db() as session:
        session.add(
            MlPubJobRun(
                job=JOB,
                scope=",".join(m.topic for m in mappings),
                started_at=started,
                finished_at=finished,
                outcome=result.outcome,
                counts=result.counts(),
                last_error=result.error[:1000] if result.error else None,
            )
        )


def run_missed_feeds(
    client: Any,
    *,
    seller_id: str,
    app_id: str,
    mappings: Sequence[intake.TopicMapping],
    keep_going: Callable[[], bool],
    deadline: datetime,
    resume: Optional[Mapping[str, Any]] = None,
    now: Callable[[], datetime] = _utcnow,
) -> MissedFeedsResult:
    """One run over every mapped topic. Never raises: a failure is in `result.error` and in the run record."""
    result = MissedFeedsResult()
    started = now()
    before = _request_counts(client)
    try:
        result.gap = _detect_gap(started)
        if result.gap:
            logger.error("missed feeds coverage gap: %s; requesting a rescan", result.gap)
            scans.request_rescan()
        _walk(
            client,
            mappings,
            resume,
            app_id=app_id,
            seller_id=seller_id,
            keep_going=keep_going,
            deadline=deadline,
            now=now,
            result=result,
        )
    except Exception as exc:  # noqa: BLE001 -- the worker keeps running; the next run retries
        logger.exception("missed feeds run failed")
        result.error = f"internal_error: {type(exc).__name__}: {exc}"[:300]
    result.requests = _delta(_request_counts(client), before)
    try:
        _record(result, mappings, started, now())
    except Exception:  # noqa: BLE001 -- observability must never fail a run
        logger.exception("could not record the missed feeds run")
    return result
