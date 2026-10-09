"""The Eventos tab: one publication's business events, newest first, a page at a time (design §3.4).

Reads ONLY `ml_item_events` (through the statement `events_query` builds for an item's timeline), so a sale, a negative
margin or any other derived fact never appears here (spec DET-5). With the `events.enabled` flag off the answer is an
empty list: the store does not write events then, and an empty tab is the honest state, never an invented one.

The Spanish label of each real event type lives here (`EVENT_LABELS`); a type that is not in the table gets the
generic one instead of failing, so a type added to `events.py` before its label shows as "Evento", not as an error.
`item_ref` and the cursor are shared with `history.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.ml_publications import events_query
from app.services.ml_publications.view import listing
from app.services.ml_publications.view.filters import FilterError

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
STATEMENT_TIMEOUT = "3s"
GENERIC_LABEL = "Evento"
CURSOR_FIELD = "cursor"

# One entry per type of `events.EVENT_TYPES` (a test pins that both lists are the same set).
EVENT_LABELS: dict[str, str] = {
    "status_paused": "Publicación pausada",
    "status_activated": "Publicación activada",
    "status_closed": "Publicación cerrada",
    "status_under_review": "Publicación en revisión",
    "status_changed_other": "Cambio de estado",
    "sub_status_changed": "Cambio de subestado",
    "stock_depleted": "Sin stock",
    "stock_replenished": "Stock repuesto",
    "price_changed": "Cambio de precio",
    "promotion_offered": "Promoción ofrecida",
    "promotion_activated": "Promoción activada",
    "promotion_finished": "Promoción finalizada",
    "promotion_price_changed": "Cambio de precio de la promoción",
    "catalog_competition_won": "Ganó la competencia de catálogo",
    "catalog_competition_lost": "Perdió la competencia de catálogo",
    "moderation_applied": "Moderación aplicada",
    "moderation_resolved": "Moderación resuelta",
    "product_link_changed": "Cambio de producto vinculado",
    "item_gone": "Publicación no encontrada en Mercado Libre",
    "item_restored": "Publicación restaurada",
    "listing_type_changed": "Cambio de tipo de publicación",
    "title_changed": "Cambio de título",
}


def label_of(event_type: str) -> str:
    return EVENT_LABELS.get(event_type, GENERIC_LABEL)


# ── Cursor: `observed_at|id`, the keyset position after the last row of a page ────────────────────────────────


def encode_cursor(observed_at: datetime, row_id: int) -> str:
    """UTC with microseconds and a `Z` (no `+`, which a query string would read as a space)."""
    return f"{observed_at.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}|{row_id}"


def decode_cursor(token: str) -> tuple[datetime, int]:
    """The position a client sent back; anything that `encode_cursor` could not have made is a 422 on `cursor`."""
    moment, separator, row_id = token.partition("|")
    try:
        if not separator or not row_id.isascii() or not row_id.isdigit():
            raise ValueError
        at = datetime.fromisoformat(moment)
        if at.tzinfo is None:
            raise ValueError
        return at, int(row_id)
    except ValueError:
        raise FilterError(CURSOR_FIELD, "cursor is not one this endpoint returned") from None


# ── Reads ─────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ItemRef:
    """What the item's entity-level history is keyed by."""

    user_product_id: Optional[str]
    family_id: Optional[int]


def item_ref(db: Session, item_id: str) -> Optional[ItemRef]:
    """The item's user product and family, or `None` when it is not a publication (unknown or never existed)."""
    row = db.execute(
        text("SELECT user_product_id, family_id FROM ml_items WHERE item_id = :item_id AND never_existed IS NOT TRUE"),
        {"item_id": item_id},
    ).first()
    return None if row is None else ItemRef(row.user_product_id, row.family_id)


@dataclass(frozen=True)
class EventsPage:
    events: list[dict[str, Any]]
    next_cursor: Optional[str]


def _event_out(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_type": row["event_type"],
        "label": label_of(row["event_type"]),
        "observed_at": row["observed_at"],
        "promotion_type": row["promotion_type"],
        "price_kind": row["price_kind"],
        "old_value": row["old_value"],
        "new_value": row["new_value"],
    }


def list_events(
    db: Session,
    item_id: str,
    *,
    enabled: bool,
    cursor: Optional[tuple[datetime, int]] = None,
    limit: int = DEFAULT_LIMIT,
) -> Optional[EventsPage]:
    """One page of the item's events, newest first; `None` when the item is not a publication.

    The statement is the one `events_query.item_timeline` runs (`item_timeline_statement`), executed here under this
    endpoint's own, tighter, time bound."""
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    listing.bound(db, STATEMENT_TIMEOUT)
    if item_ref(db, item_id) is None:
        return None
    if not enabled:
        return EventsPage([], None)
    position = events_query.Cursor(*cursor) if cursor else None
    statement = events_query.item_timeline_statement(item_id, cursor=position, limit=limit, newest_first=True)
    rows = db.execute(text(statement.sql), statement.params).mappings().all()
    page = rows[:limit]
    more = encode_cursor(page[-1]["observed_at"], page[-1]["id"]) if len(rows) > limit else None
    return EventsPage([_event_out(row) for row in page], more)
