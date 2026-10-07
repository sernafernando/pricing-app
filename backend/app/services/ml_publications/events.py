"""Pure business-event rules over a stored change-log row (design D15, D16).

`derive_events` sees only the row (`changes` + `context`, both written by the store at the
moment of the change), never the current state, so the same function serves the live
write and the re-derivation of events from the change log alone (spec Domain 5). It is
called only for rows that were actually written: a first sighting or a noise-only diff has
no row and therefore no event. No I/O here; persistence lives in `events_store`.

Covers the item core and the price events (`price_changed` kinds standard, promotion, sale);
other resources add their rules with their PRs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

ITEM_RESOURCE = "item"
PRODUCT_LINK_RESOURCE = "product_link"
PRICES_RESOURCE = "prices"
SALE_PRICE_RESOURCE = "sale_price"
PRICE_CHANGED = "price_changed"
# Row kinds that carry a state change; `gone` rows say the resource vanished, not that a price moved.
_CHANGE_KINDS = ("change", "restored")

STATUS_EVENT_BY_VALUE = {
    "paused": "status_paused",
    "active": "status_activated",
    "closed": "status_closed",
    "under_review": "status_under_review",
}
STATUS_EVENT_OTHER = "status_changed_other"


@dataclass(frozen=True)
class ChangeRow:
    """The columns of a change-log row the rules and the event writer read."""

    id: int
    resource_type: str
    item_id: Optional[str]
    kind: str
    observed_at: datetime
    source_last_updated: Optional[datetime]
    changes: Sequence[Mapping[str, Any]]
    context: Mapping[str, Any]

    @classmethod
    def from_model(cls, entry: Any) -> "ChangeRow":
        return cls(
            id=entry.id,
            resource_type=entry.resource_type,
            item_id=entry.item_id,
            kind=entry.kind,
            observed_at=entry.observed_at,
            source_last_updated=entry.source_last_updated,
            changes=entry.changes or [],
            context=entry.context or {},
        )


@dataclass(frozen=True)
class Event:
    event_type: str
    item_id: str
    old_value: Any = None
    new_value: Any = None
    payload: dict = field(default_factory=dict)
    promotion_id: Optional[str] = None
    promotion_type: Optional[str] = None
    price_kind: Optional[str] = None

    @property
    def promotion_key(self) -> Optional[str]:
        """Part of the event identity when it applies (later resources)."""
        if self.promotion_id is None and self.promotion_type is None:
            return None
        return f"{self.promotion_id or ''}:{self.promotion_type or ''}"


def dedupe_key(change_log_id: int, event_type: str, promotion_key: Optional[str], price_kind: Optional[str]) -> bytes:
    """Identity of an event: originating row, type, promotion key and price kind (D8).

    ML `last_updated` is deliberately not part of it. Each part is length-prefixed so a
    value containing the separator cannot collide with a different split of the same text.
    """
    parts = (str(change_log_id), event_type, promotion_key or "", price_kind or "")
    return hashlib.sha256("|".join(f"{len(p)}:{p}" for p in parts).encode("utf-8")).digest()


def _change(changes: Sequence[Mapping[str, Any]], path: str) -> Optional[Mapping[str, Any]]:
    for change in changes:
        if change.get("p") == path:
            return change
    return None


def _touches(changes: Sequence[Mapping[str, Any]], path: str) -> bool:
    """True when a change is at `path` or at a member of the set/array under it (`path[...]`)."""
    return any(c.get("p") == path or str(c.get("p", "")).startswith(f"{path}[") for c in changes)


def _status_events(row: ChangeRow) -> list[Event]:
    ctx = row.context
    old, new = ctx.get("status_old"), ctx.get("status_new")
    item_id = row.item_id or ""
    if new is None or old == new:
        if _touches(row.changes, "sub_status") and new is not None:
            return [
                Event(
                    "sub_status_changed",
                    item_id,
                    old_value=ctx.get("sub_status_old"),
                    new_value=ctx.get("sub_status_new"),
                    payload={"status": new},
                )
            ]
        return []
    event_type = STATUS_EVENT_BY_VALUE.get(new, STATUS_EVENT_OTHER)
    if event_type == "status_activated":
        payload: dict = {"is_reactivation": ctx.get("first_active_at_before") is not None}
    else:
        payload = {"old_sub_status": ctx.get("sub_status_old"), "new_sub_status": ctx.get("sub_status_new")}
    return [Event(event_type, item_id, old_value=old, new_value=new, payload=payload)]


def _field_event(row: ChangeRow, event_type: str, path: str) -> list[Event]:
    change = _change(row.changes, path)
    if change is None or change.get("op") != "replace":
        return []
    return [Event(event_type, row.item_id or "", old_value=change.get("old"), new_value=change.get("new"))]


def _stock_events(row: ChangeRow) -> list[Event]:
    old, new = row.context.get("available_quantity_old"), row.context.get("available_quantity_new")
    if not isinstance(old, int) or not isinstance(new, int) or isinstance(old, bool) or isinstance(new, bool):
        return []
    if old > 0 and new == 0:
        event_type = "stock_depleted"
    elif old == 0 and new > 0:
        event_type = "stock_replenished"
    else:
        return []
    sold = _change(row.changes, "sold_quantity")
    payload = {"sold_quantity": sold.get("new") if sold else None}
    return [Event(event_type, row.item_id or "", old_value=old, new_value=new, payload=payload)]


def _product_link_events(row: ChangeRow) -> list[Event]:
    """`product_link_changed` from a `product_link` row (design D20): old/new product, sources in the payload.

    The only event whose inputs include our product catalog; everything it needs was written into
    the row's `context` at the moment of the change.
    """
    ctx = row.context
    payload = {
        key: ctx.get(key)
        for key in (
            "variation_id",
            "source_old",
            "source_new",
            "match_status_old",
            "match_status_new",
            "matched_sku",
            "sku_field",
            "linked_by",
        )
    }
    return [
        Event(
            "product_link_changed",
            row.item_id or "",
            old_value=ctx.get("producto_item_id_old"),
            new_value=ctx.get("producto_item_id_new"),
            payload=payload,
        )
    ]


def _entries(row: ChangeRow) -> tuple[Optional[Mapping[str, Any]], Optional[Mapping[str, Any]]]:
    entries = row.context.get("entries")
    if not isinstance(entries, Mapping):
        return None, None
    old, new = entries.get("old"), entries.get("new")
    return (old if isinstance(old, Mapping) else None, new if isinstance(new, Mapping) else None)


def _side(entries: Optional[Mapping[str, Any]], kind: str) -> Optional[Mapping[str, Any]]:
    entry = entries.get(kind) if entries else None
    return entry if isinstance(entry, Mapping) else None


def _promotion_identity(entry: Optional[Mapping[str, Any]]) -> Optional[tuple]:
    """What makes a promotion price "changed": amount and promotion metadata, not the ML price entry id."""
    if entry is None:
        return None
    return (entry.get("amount"), entry.get("promotion_id"), entry.get("promotion_type"))


def _prices_events(row: ChangeRow) -> list[Event]:
    """Standard and promotion price changes of the marketplace channel (design D16)."""
    old, new = _entries(row)
    if old is None and new is None:
        return []
    item_id = row.item_id or ""
    events: list[Event] = []
    old_standard, new_standard = _side(old, "standard"), _side(new, "standard")
    old_amount = old_standard.get("amount") if old_standard else None
    new_amount = new_standard.get("amount") if new_standard else None
    if old_amount != new_amount:
        shown = new_standard or old_standard or {}
        events.append(
            Event(
                PRICE_CHANGED,
                item_id,
                old_value=old_amount,
                new_value=new_amount,
                payload={"currency_id": shown.get("currency_id"), "price_id": shown.get("price_id")},
                price_kind="standard",
            )
        )
    old_promotion, new_promotion = _side(old, "promotion"), _side(new, "promotion")
    if _promotion_identity(old_promotion) != _promotion_identity(new_promotion):
        shown = new_promotion or old_promotion or {}
        events.append(
            Event(
                PRICE_CHANGED,
                item_id,
                old_value=old_promotion.get("amount") if old_promotion else None,
                new_value=new_promotion.get("amount") if new_promotion else None,
                payload={"price_id": shown.get("price_id")},
                promotion_id=shown.get("promotion_id"),
                promotion_type=shown.get("promotion_type"),
                price_kind="promotion",
            )
        )
    return events


def _sale_price_events(row: ChangeRow) -> list[Event]:
    """The price the buyer pays moved: `amount` of `sale_price` changed (design D16, kind `sale`)."""
    old, new = _entries(row)
    if old is None and new is None:
        return []
    old_amount = old.get("amount") if old else None
    new_amount = new.get("amount") if new else None
    if old_amount == new_amount:
        return []
    shown = new or old or {}
    # The promotion involved: the one in force after the change, else the one that just ended.
    promotion = new if new and (new.get("promotion_id") or new.get("promotion_type")) else (old or {})
    return [
        Event(
            PRICE_CHANGED,
            row.item_id or "",
            old_value=old_amount,
            new_value=new_amount,
            payload={"regular_amount": shown.get("regular_amount"), "currency_id": shown.get("currency_id")},
            promotion_id=promotion.get("promotion_id"),
            promotion_type=promotion.get("promotion_type"),
            price_kind="sale",
        )
    ]


def derive_events(row: ChangeRow) -> list[Event]:
    """Typed events of one change-log row; empty when the change maps to none."""
    if row.resource_type == PRODUCT_LINK_RESOURCE:
        return _product_link_events(row)
    if row.resource_type in (PRICES_RESOURCE, SALE_PRICE_RESOURCE):
        if row.kind not in _CHANGE_KINDS:
            return []
        return _prices_events(row) if row.resource_type == PRICES_RESOURCE else _sale_price_events(row)
    if row.resource_type != ITEM_RESOURCE:
        return []
    item_id = row.item_id or ""
    events: list[Event] = []
    if row.kind == "gone":
        events.append(Event("item_gone", item_id, payload={"last_status": row.context.get("status_old")}))
    elif row.kind == "restored":
        events.append(Event("item_restored", item_id, payload={"status": row.context.get("status_new")}))
    events += _status_events(row)
    events += _field_event(row, "listing_type_changed", "listing_type_id")
    events += _field_event(row, "title_changed", "title")
    events += _stock_events(row)
    return events
