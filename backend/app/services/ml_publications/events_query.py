"""Read interface over `ml_item_events` (spec "Event queryability"; no UI, no HTTP here).

Three indexed access paths (design D15): an item's timeline (`ix_ml_item_events_item`),
an event type over a date range (`ix_ml_item_events_type`) and an official store with a
type and range (`ix_ml_item_events_store`). The brand filter applies on top of those.
Store and brand are the values denormalized on the event, so an item that changed store
later still matches the store it had when the event happened.

Pagination is keyset on `(observed_at, id)`: a page request carries the cursor of the last
row it saw, so rows written between two requests can neither shift nor duplicate a page.
Read-only; never deletes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
STATEMENT_TIMEOUT = "10s"

_COLUMNS = (
    "id, event_type, item_id, promotion_id, promotion_type, price_kind, old_value, new_value, payload,"
    " observed_at, source_last_updated, official_store_id, brand, change_log_id"
)


@dataclass(frozen=True)
class Cursor:
    """Position after the last row of a page."""

    observed_at: datetime
    id: int


@dataclass(frozen=True)
class EventView:
    id: int
    event_type: str
    item_id: str
    promotion_id: Optional[str]
    promotion_type: Optional[str]
    price_kind: Optional[str]
    old_value: Any
    new_value: Any
    payload: dict
    observed_at: datetime
    source_last_updated: Optional[datetime]
    official_store_id: Optional[int]
    brand: Optional[str]
    change_log_id: int


@dataclass(frozen=True)
class EventPage:
    events: list[EventView]
    next_cursor: Optional[Cursor]  # None on the last page


@dataclass(frozen=True)
class Statement:
    sql: str
    params: dict


def _checked_limit(limit: int) -> int:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    return min(limit, MAX_LIMIT)


def _order_and_cursor(conditions: list[str], params: dict, cursor: Optional[Cursor], newest_first: bool) -> str:
    if cursor is not None:
        operator = "<" if newest_first else ">"
        conditions.append(f"(observed_at, id) {operator} (:cursor_at, :cursor_id)")
        params.update(cursor_at=cursor.observed_at, cursor_id=cursor.id)
    return "ORDER BY observed_at DESC, id DESC" if newest_first else "ORDER BY observed_at, id"


def _build(conditions: list[str], params: dict, order: str, limit: int) -> Statement:
    # One extra row tells whether another page exists without a count.
    params["row_limit"] = limit + 1
    return Statement(
        f"SELECT {_COLUMNS} FROM ml_item_events WHERE {' AND '.join(conditions)} {order} LIMIT :row_limit", params
    )


def item_timeline_statement(
    item_id: str, *, cursor: Optional[Cursor] = None, limit: int = DEFAULT_LIMIT, newest_first: bool = False
) -> Statement:
    conditions, params = ["item_id = :item_id"], {"item_id": item_id}
    order = _order_and_cursor(conditions, params, cursor, newest_first)
    return _build(conditions, params, order, _checked_limit(limit))


def search_statement(
    *,
    event_type: Optional[str] = None,
    official_store_id: Optional[int] = None,
    brand: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    cursor: Optional[Cursor] = None,
    limit: int = DEFAULT_LIMIT,
    newest_first: bool = True,
) -> Statement:
    if event_type is None and official_store_id is None:
        raise ValueError("a search needs event_type or official_store_id (the indexed access paths)")
    conditions: list[str] = []
    params: dict = {}
    for column, value in (("event_type", event_type), ("official_store_id", official_store_id), ("brand", brand)):
        if value is not None:
            conditions.append(f"{column} = :{column}")
            params[column] = value
    if since is not None:
        conditions.append("observed_at >= :since")
        params["since"] = since
    if until is not None:
        conditions.append("observed_at < :until")
        params["until"] = until
    order = _order_and_cursor(conditions, params, cursor, newest_first)
    return _build(conditions, params, order, _checked_limit(limit))


def _run(db, statement: Statement, limit: int) -> EventPage:
    db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    rows = db.execute(text(statement.sql), statement.params).mappings().all()
    page_size = statement.params["row_limit"] - 1
    events = [EventView(**dict(row)) for row in rows[:page_size]]
    has_more = len(rows) > page_size
    last = events[-1] if events else None
    return EventPage(events, Cursor(last.observed_at, last.id) if has_more and last else None)


def item_timeline(
    db,
    item_id: str,
    *,
    cursor: Optional[Cursor] = None,
    limit: int = DEFAULT_LIMIT,
    newest_first: bool = False,
) -> EventPage:
    """All events of one item, chronological by default, one page."""
    statement = item_timeline_statement(item_id, cursor=cursor, limit=limit, newest_first=newest_first)
    return _run(db, statement, limit)


def search_events(
    db,
    *,
    event_type: Optional[str] = None,
    official_store_id: Optional[int] = None,
    brand: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    cursor: Optional[Cursor] = None,
    limit: int = DEFAULT_LIMIT,
    newest_first: bool = True,
) -> EventPage:
    """Events across items by type and/or store (with optional brand and `[since, until)`), newest first."""
    statement = search_statement(
        event_type=event_type,
        official_store_id=official_store_id,
        brand=brand,
        since=since,
        until=until,
        cursor=cursor,
        limit=limit,
        newest_first=newest_first,
    )
    return _run(db, statement, limit)
