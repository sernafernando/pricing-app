"""Persistence of business events (design D15): write for one change-log row, or rebuild.

`write_events` runs inside the transaction that inserted the change-log row, so an event
never exists without its row (and the other way round when events are on). The unique
`dedupe_key` plus `ON CONFLICT DO NOTHING` make writing the events of a row twice a
no-op. `rederive_events` rebuilds events from stored change-log rows alone: it reads no
current state, so a corrected rule can be replayed over the whole history. It never
deletes anything.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.ml_publications import MlChangeLog, MlItemEvent
from app.services import promo_refresh_queue
from app.services.ml_publications.events import ChangeRow, Event, dedupe_key, derive_events

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500
# One INSERT per batch: a row yields at most a handful of events of 14 columns each, so the cap keeps the
# statement far below Postgres' 65535 bind-parameter limit.
MAX_BATCH_SIZE = 500
BATCH_STATEMENT_TIMEOUT = "30s"


def _values(row: ChangeRow, event: Event) -> dict:
    context = row.context
    return {
        "event_type": event.event_type,
        "item_id": event.item_id,
        "promotion_id": event.promotion_id,
        "promotion_type": event.promotion_type,
        "price_kind": event.price_kind,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "payload": event.payload,
        "observed_at": row.observed_at,
        "source_last_updated": row.source_last_updated,
        "official_store_id": context.get("official_store_id"),
        "brand": context.get("brand"),
        "change_log_id": row.id,
        "dedupe_key": dedupe_key(row.id, event.event_type, event.promotion_key, event.price_kind),
    }


def _insert(db, rows: list[ChangeRow]) -> list:
    """One INSERT for the events of every row given; returns the new ones (type, item, payload)."""
    values = [_values(row, event) for row in rows for event in derive_events(row)]
    if not values:
        return []
    statement = (
        pg_insert(MlItemEvent)
        .values(values)
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(MlItemEvent.event_type, MlItemEvent.item_id, MlItemEvent.payload)
    )
    return list(db.execute(statement).all())


def write_events(db, entry: MlChangeLog) -> int:
    """Insert the events of one change-log row; returns how many were new.

    A NEW `status_activated` event that is a reactivation also queues the item's promotions-mirror refresh,
    in this same transaction (the owner's rule: promotions are asked about again once the item is active
    again). Only here: `rederive_events` replays history and must not refresh anything."""
    created = _insert(db, [ChangeRow.from_model(entry)])
    reactivated = [
        event.item_id
        for event in created
        if event.event_type == "status_activated" and (event.payload or {}).get("is_reactivation") is True
    ]
    if reactivated:
        try:
            with db.begin_nested():  # a queue problem must never roll back the change-log row and its events
                promo_refresh_queue.enqueue(db, reactivated, datetime.now(timezone.utc))
        except Exception:  # noqa: BLE001
            logger.exception("promo refresh enqueue failed for %s; the events are kept", reactivated)
    return len(created)


def batch_query(db, *, item_id: Optional[str], last_id: int, batch_size: int):
    """The next batch of change-log rows after `last_id`, in id order, optionally one item's."""
    query = db.query(MlChangeLog).filter(MlChangeLog.id > last_id)
    if item_id is not None:
        query = query.filter(MlChangeLog.item_id == item_id)
    return query.order_by(MlChangeLog.id).limit(batch_size)


def rederive_events(db, *, item_id: Optional[str] = None, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Rebuild the events of every stored change-log row (optionally one item's); returns new events.

    Keyset-paged by row id so memory stays bounded, one transaction per batch (committed, with
    its own `statement_timeout`) so a long history never holds one long transaction and a late
    failure keeps the earlier batches; existing events are left alone. `item_id` narrows the scan to
    one item's rows (a handful), whichever index the planner picks.
    """
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    created = 0
    last_id = 0
    while True:
        db.execute(text(f"SET LOCAL statement_timeout = '{BATCH_STATEMENT_TIMEOUT}'"))
        entries = batch_query(db, item_id=item_id, last_id=last_id, batch_size=batch_size).all()
        if not entries:
            db.commit()  # close the transaction opened by the batch's SET LOCAL
            return created
        created += len(_insert(db, [ChangeRow.from_model(entry) for entry in entries]))
        last_id = entries[-1].id
        db.commit()  # ends the batch transaction; also expires the loaded rows (bounded identity map)
