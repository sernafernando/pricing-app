"""Notification intake from the bridge `webhook_latest` (design D13).

The bridge keeps ONE row per `(topic, resource)` (the latest delivery), so repeated events for a
resource are already collapsed. Per mapped topic a pass does two things, each in its own short,
read-only bridge transaction:

1. forward pass: rows strictly after the persisted `(received_at, resource)` cursor, in keyset
   batches. A full batch always advances the cursor, so the pass can never stall on the same rows;
2. overlap pass: a bounded re-read of the window just behind the cursor, to catch rows that
   committed late (`received_at` is the bridge transaction's start time). It never moves the
   cursor; rows beyond its limit are left to rescans and counted as `overlap_truncated`.

The pricing side then parses the resource into an item id, drops other sellers' rows and rows
whose state was already fetched after the notification, and enqueues the rest (lane 1). The
cursor moves in the SAME transaction as the enqueue, so a failed enqueue re-reads the rows.

Intake NEVER writes to the bridge: its connection is a `READ ONLY` transaction.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.core import database
from app.core.config import settings
from app.services.ml_publications import queue
from app.services.ml_publications.resources import (
    BUNDLE_RESOURCE,
    CORE_RESOURCE,
    PROMOTIONS_RESOURCE,
    REFRESH_RESOURCES,
)

logger = logging.getLogger(__name__)

ITEM_KIND = "item"
BRIDGE_STATEMENT_TIMEOUT = "10s"
ERROR_BRIDGE_UNAVAILABLE = "bridge_unavailable"
ERROR_SELLER_NOT_CONFIGURED = "seller_not_configured"

# Exact production topic names and the resource strings captured for them (2026-10-06). `stock-locations`
# and `user-products-families` are deliberately absent: the capture has no sample of either, so their
# pattern must be fixed from a real row before they can be mapped (spec "Intake from webhook_latest").
TOPIC_PATTERNS: Mapping[str, "re.Pattern[str]"] = {
    "items": re.compile(r"^/items/(MLA\d+)$"),
    "items_prices": re.compile(r"^/items/(MLA\d+)/prices$"),
    "catalog_item_competition_status": re.compile(r"^/items/(MLA\d+)/price_to_win$"),
    "public_offers": re.compile(r"^/seller-promotions/offers/OFFER-(MLA\d+)-\d+$"),
    "public_candidates": re.compile(r"^/seller-promotions/candidates/CANDIDATE-(MLA\d+)-\d+$"),
}

# Entries whose resources are covered by the item core fetch can be judged "already satisfied" from
# `ml_items.fetched_request_started_at`; sub-resources have no state of their own in this PR.
_CORE_COVERED = frozenset({BUNDLE_RESOURCE, CORE_RESOURCE})


@dataclass(frozen=True)
class TopicMapping:
    topic: str
    kind: str
    resources: Tuple[str, ...]

    @property
    def core_covered(self) -> bool:
        return set(self.resources) <= _CORE_COVERED

    @property
    def debounce(self) -> Optional[timedelta]:
        """Delay before an entry of this mapping may be claimed. `public_offers` / `public_candidates` arrive in
        bursts per item (about 170 distinct items per hour on 2026-10-06): a promotions-only entry waits
        `ML_PUB_PROMOTIONS_DEBOUNCE_SECONDS` (default 60 s) after the notification, so the burst collapses on the
        queue key into one fetch (design D14; with the 300 s minimum age, about 0.05 req/s)."""
        seconds = settings.ML_PUB_PROMOTIONS_DEBOUNCE_SECONDS
        return timedelta(seconds=seconds) if seconds > 0 and self.resources == (PROMOTIONS_RESOURCE,) else None


def topic_mappings(setting_value: Any) -> List[TopicMapping]:
    """Validate the `intake.topics` setting into mappings. A topic with no known pattern, a bad entry
    or an unknown resource name is skipped with a warning: it can never be read."""
    mappings: List[TopicMapping] = []
    if not isinstance(setting_value, Mapping):
        return mappings
    for topic, entry in setting_value.items():
        resources = entry.get("resources") if isinstance(entry, Mapping) else None
        valid = (
            (
                topic in TOPIC_PATTERNS
                and entry.get("kind") == ITEM_KIND
                and isinstance(resources, list)
                and resources
                and all(isinstance(r, str) and r in REFRESH_RESOURCES for r in resources)
            )
            if isinstance(entry, Mapping)
            else False
        )
        if not valid:
            logger.warning("intake topic %r is not mappable (no fixed pattern or invalid entry); skipped", topic)
            continue
        mappings.append(TopicMapping(topic=topic, kind=ITEM_KIND, resources=tuple(sorted(set(resources)))))
    return mappings


def parse_resource(topic: str, resource: str) -> Optional[str]:
    """The item id a notification resource points at, or None when it does not match the topic's pattern."""
    pattern = TOPIC_PATTERNS.get(topic)
    match = pattern.match(resource or "") if pattern else None
    return match.group(1) if match else None


@dataclass
class IntakeStats:
    rows_read: int = 0
    enqueued: int = 0
    skipped_satisfied: int = 0
    skipped_foreign_seller: int = 0
    unparsed: int = 0
    batches: int = 0
    overlap_rows: int = 0
    overlap_enqueued: int = 0
    overlap_truncated: int = 0
    cursor_conflicts: int = 0

    def as_dict(self) -> Dict[str, int]:
        return dict(vars(self))


@dataclass
class IntakeResult:
    stats: IntakeStats = field(default_factory=IntakeStats)
    error: Optional[str] = None


class OverlapMemory:
    """The `(resource, received_at)` rows of each topic that were already enqueued, so the overlap
    window (re-read every pass) does not enqueue them again: every re-enqueue bumps the entry
    `version` and can requeue a claim that is being fetched. A new delivery of the same resource has
    a new `received_at`, so it is not remembered. In-process and bounded by the overlap window; a
    restart only costs one harmless repeat."""

    def __init__(self) -> None:
        self._seen: Dict[str, set] = {}

    def add(self, topic: str, rows: Sequence[NotificationRow]) -> None:
        self._seen.setdefault(topic, set()).update((r.resource, r.received_at) for r in rows)

    def unseen(self, topic: str, rows: Sequence[NotificationRow]) -> List[NotificationRow]:
        seen = self._seen.get(topic, ())
        return [r for r in rows if (r.resource, r.received_at) not in seen]

    def prune(self, topic: str, older_than: datetime) -> None:
        if topic in self._seen:
            self._seen[topic] = {key for key in self._seen[topic] if key[1] >= older_than}

    def size(self) -> int:
        return sum(len(rows) for rows in self._seen.values())


@dataclass(frozen=True)
class NotificationRow:
    resource: str
    received_at: datetime
    user_id: Optional[str]


class _BridgeUnavailable(Exception):
    pass


@contextmanager
def open_read_only(engine: Engine) -> Iterator[Connection]:
    """A bridge connection inside a READ ONLY transaction with a statement timeout; it is rolled back
    on exit. The bridge cannot be written through it."""
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text(f"SET LOCAL statement_timeout = '{BRIDGE_STATEMENT_TIMEOUT}'"))
        try:
            yield conn
        finally:
            conn.rollback()


_SELECT = (
    "SELECT resource, received_at, payload->>'user_id' AS user_id FROM webhook_latest "
    "WHERE topic = :topic AND {where} ORDER BY received_at {direction}, resource {direction} LIMIT :limit"
)
_FORWARD = _SELECT.format(where="(received_at, resource) > (CAST(:at AS timestamptz), :res)", direction="ASC")
# Newest first: when the window holds more rows than the limit, the rows dropped are the OLDEST ones,
# not the late arrivals nearest the cursor (the index is (topic, received_at DESC, resource DESC)).
_OVERLAP = _SELECT.format(
    where="received_at >= CAST(:lower AS timestamptz) AND (received_at, resource) <= (CAST(:at AS timestamptz), :res)",
    direction="DESC",
)


def _read(bridge: Callable[[], Engine], statement: str, params: Mapping[str, Any]) -> List[NotificationRow]:
    try:
        with open_read_only(bridge()) as conn:
            rows = conn.execute(text(statement), params).all()
    except Exception as exc:  # noqa: BLE001 -- the bridge being down must never crash the worker
        logger.error("intake could not read the bridge webhook_latest: %s", exc)
        raise _BridgeUnavailable from exc
    return [NotificationRow(r.resource, r.received_at, None if r.user_id is None else str(r.user_id)) for r in rows]


# --- pricing side ---------------------------------------------------------------------------------

_INIT_CURSOR = text(
    "INSERT INTO ml_pub_intake_cursors (topic, cursor_received_at, cursor_resource, updated_at) "
    "VALUES (:topic, :at, '', now()) ON CONFLICT (topic) DO NOTHING"
)
_LOAD_CURSOR = text("SELECT cursor_received_at, cursor_resource FROM ml_pub_intake_cursors WHERE topic = :topic")
_ADVANCE_CURSOR = text(
    """
    UPDATE ml_pub_intake_cursors SET
        cursor_received_at = :at, cursor_resource = :res, updated_at = now(),
        rows_read = COALESCE(rows_read, 0) + :rows_read,
        enqueued = COALESCE(enqueued, 0) + :enqueued,
        skipped_satisfied = COALESCE(skipped_satisfied, 0) + :satisfied,
        skipped_foreign_seller = COALESCE(skipped_foreign_seller, 0) + :foreign,
        unparsed = COALESCE(unparsed, 0) + :unparsed
    WHERE topic = :topic
      AND (cursor_received_at IS NULL
           OR (cursor_received_at, COALESCE(cursor_resource, '')) < (CAST(:at AS timestamptz), :res))
    """
)
_FETCHED = text("SELECT item_id, fetched_request_started_at FROM ml_items WHERE item_id = ANY(:ids)")


@dataclass
class Classified:
    entries: List[queue.EnqueueEntry] = field(default_factory=list)
    satisfied: int = 0
    foreign: int = 0
    unparsed: int = 0


def classify(
    session: Session,
    mapping: TopicMapping,
    rows: Sequence[NotificationRow],
    seller_id: str,
    lane: int = queue.LANE_NOTIFICATION,
) -> Classified:
    """Turn notification rows of one topic into queue entries of `lane`. Shared with `/missed_feeds`
    recovery, which enqueues in the reconcile lane through this very rule (foreign seller, topic parser,
    "already fetched after the notification")."""
    out = Classified()
    candidates: List[Tuple[str, NotificationRow]] = []
    for row in rows:
        if row.user_id != seller_id:
            out.foreign += 1
            continue
        item_id = parse_resource(mapping.topic, row.resource)
        if item_id is None:
            out.unparsed += 1
            continue
        candidates.append((item_id, row))
    fetched: Dict[str, Optional[datetime]] = {}
    if candidates and mapping.core_covered:
        ids = sorted({item_id for item_id, _ in candidates})
        fetched = {r.item_id: r.fetched_request_started_at for r in session.execute(_FETCHED, {"ids": ids})}
    for item_id, row in candidates:
        started = fetched.get(item_id)
        if started is not None and started >= row.received_at:
            out.satisfied += 1
            continue
        out.entries.append(
            queue.EnqueueEntry(
                kind=mapping.kind,
                entity_id=item_id,
                lane=lane,
                resources=mapping.resources,
                source_received_at=row.received_at,
                not_before=row.received_at + mapping.debounce if mapping.debounce else None,
            )
        )
    return out


def _load_or_init_cursor(mapping: TopicMapping, start: datetime) -> Tuple[datetime, str, bool]:
    """(cursor_at, cursor_resource, existed). A first run starts at `start`: history before intake
    was enabled is the backfill scan's job, not intake's."""
    with database.get_background_db() as session:
        found = session.execute(_LOAD_CURSOR, {"topic": mapping.topic}).first()
        if found and found.cursor_received_at is not None:
            return found.cursor_received_at, found.cursor_resource or "", True
        session.execute(_INIT_CURSOR, {"topic": mapping.topic, "at": start})
    return start, "", False


def _forward(
    mapping: TopicMapping,
    cursor: Tuple[datetime, str],
    *,
    bridge: Callable[[], Engine],
    seller_id: str,
    batch: int,
    keep_going: Callable[[], bool],
    stats: IntakeStats,
    memory: OverlapMemory,
) -> Tuple[datetime, str]:
    """Returns the cursor the topic ended at."""
    at_, resource = cursor
    while keep_going():
        rows = _read(bridge, _FORWARD, {"topic": mapping.topic, "at": at_, "res": resource, "limit": batch})
        if not rows:
            break
        with database.get_background_db() as session:
            classified = classify(session, mapping, rows, seller_id)
            last = rows[-1]
            # Cursor first, enqueue second, one transaction: any failure rolls both back. The advance only
            # moves the cursor forward: a second intake process that got further is never pulled back.
            moved = session.execute(
                _ADVANCE_CURSOR,
                {
                    "topic": mapping.topic,
                    "at": last.received_at,
                    "res": last.resource,
                    "rows_read": len(rows),
                    "enqueued": len(classified.entries),
                    "satisfied": classified.satisfied,
                    "foreign": classified.foreign,
                    "unparsed": classified.unparsed,
                },
            )
            if moved.rowcount == 0:
                # Another intake process is already past these rows and enqueued them with its own
                # cursor commit: re-enqueueing would only bump entry versions. Stop this topic.
                session.rollback()
                stats.cursor_conflicts += 1
                break
            queue.enqueue(classified.entries, session=session)
        memory.add(mapping.topic, rows)
        stats.batches += 1
        stats.rows_read += len(rows)
        stats.enqueued += len(classified.entries)
        stats.skipped_satisfied += classified.satisfied
        stats.skipped_foreign_seller += classified.foreign
        stats.unparsed += classified.unparsed
        at_, resource = last.received_at, last.resource
        if len(rows) < batch:
            break
    return at_, resource


def _overlap(
    mapping: TopicMapping,
    cursor: Tuple[datetime, str],
    *,
    bridge: Callable[[], Engine],
    seller_id: str,
    overlap_seconds: int,
    overlap_batch: int,
    stats: IntakeStats,
    memory: OverlapMemory,
) -> None:
    at_, resource = cursor
    lower = at_ - timedelta(seconds=overlap_seconds)
    memory.prune(mapping.topic, lower)
    rows = _read(
        bridge,
        _OVERLAP,
        {
            "topic": mapping.topic,
            "lower": lower,
            "at": at_,
            "res": resource,
            "limit": overlap_batch + 1,
        },
    )
    if len(rows) > overlap_batch:
        stats.overlap_truncated += 1
        rows = rows[:overlap_batch]
    rows = memory.unseen(mapping.topic, rows)
    stats.overlap_rows += len(rows)
    if not rows:
        return
    with database.get_background_db() as session:
        classified = classify(session, mapping, rows, seller_id)
        queue.enqueue(classified.entries, session=session)
    memory.add(mapping.topic, rows)
    stats.overlap_enqueued += len(classified.entries)


def run_pass(
    mappings: Sequence[TopicMapping],
    *,
    bridge_engine: Callable[[], Engine],
    seller_id: Optional[str],
    batch: int = 1000,
    overlap_seconds: int = 120,
    overlap_batch: int = 2000,
    keep_going: Callable[[], bool] = lambda: True,
    now: Optional[datetime] = None,
    memory: Optional[OverlapMemory] = None,
) -> IntakeResult:
    """One intake pass over every mapped topic. Never raises: a bridge or pricing failure is reported
    in `IntakeResult.error` and leaves the cursor of the failed batch where it was."""
    result = IntakeResult()
    memory = memory if memory is not None else OverlapMemory()
    if not seller_id:
        logger.error("ML_USER_ID is not set; intake refuses to read notifications without a seller scope")
        result.error = ERROR_SELLER_NOT_CONFIGURED
        return result
    start = (now or datetime.now(timezone.utc)) - timedelta(seconds=overlap_seconds)
    try:
        for mapping in mappings:
            if not keep_going():
                break
            at_, resource, existed = _load_or_init_cursor(mapping, start)
            end_at, _end_resource = _forward(
                mapping,
                (at_, resource),
                bridge=bridge_engine,
                seller_id=str(seller_id),
                batch=batch,
                keep_going=keep_going,
                stats=result.stats,
                memory=memory,
            )
            if existed and keep_going():
                _overlap(
                    mapping,
                    (at_, resource),
                    bridge=bridge_engine,
                    seller_id=str(seller_id),
                    overlap_seconds=overlap_seconds,
                    overlap_batch=overlap_batch,
                    stats=result.stats,
                    memory=memory,
                )
            # Rows behind the NEXT pass's overlap window can never be re-read: forget them.
            memory.prune(mapping.topic, end_at - timedelta(seconds=overlap_seconds))
    except _BridgeUnavailable:
        result.error = ERROR_BRIDGE_UNAVAILABLE
    except Exception as exc:  # noqa: BLE001 -- a failed batch rolled back; retry on the next interval
        logger.exception("intake pass failed")
        result.error = f"intake_failed: {type(exc).__name__}: {exc}"[:300]
    return result
