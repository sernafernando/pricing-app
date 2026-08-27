"""Pure mapping from raw ML API payloads to ops DTOs.

No I/O, no DB — fully unit-testable against fixtures (design doc, obs
#1823, `Ingestion Architecture`). `map_order`/`map_shipment` NEVER raise;
they return either a populated DTO or a `MappingError`, so a caller can
never observe a partially-populated DTO (fail-closed contract, design D7:
"a partially-mapped order persisted as truth is worse than an absent one").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from dateutil.parser import isoparse


class MappingError:
    """Non-exception failure value returned by `map_order`/`map_shipment`.

    Deliberately NOT raised: the fail-closed contract is expressed as a
    return-value union (`OrderOpsDTO | MappingError`), so a caller cannot
    accidentally let an exception propagate past a partially-built DTO —
    there is no partially-built DTO to leak, ever.
    """

    __slots__ = ("reason", "raw_payload")

    def __init__(self, reason: str, raw_payload: Optional[Dict[str, Any]] = None) -> None:
        self.reason = reason
        self.raw_payload = raw_payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"MappingError(reason={self.reason!r})"


@dataclass(frozen=True)
class OrderItemOpsDTO:
    item_id: str
    variation_id: Optional[int]
    seller_sku: Optional[str]
    title: Optional[str]
    quantity: Optional[int]
    unit_price: Optional[float]
    full_unit_price: Optional[float]
    sale_fee: Optional[float]
    listing_type_id: Optional[str]
    raw_item: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderOpsDTO:
    order_id: int
    seller_id: int
    ml_last_updated: datetime
    pack_id: Optional[int]
    status: Optional[str]
    status_detail: Optional[str]
    date_created: Optional[datetime]
    date_closed: Optional[datetime]
    buyer_id: Optional[int]
    buyer_nickname: Optional[str]
    total_amount: Optional[float]
    paid_amount: Optional[float]
    currency_id: Optional[str]
    shipping_id: Optional[int]
    tags: List[Any] = field(default_factory=list)
    raw_order: Dict[str, Any] = field(default_factory=dict)
    items: List[OrderItemOpsDTO] = field(default_factory=list)


@dataclass(frozen=True)
class ShipmentOpsDTO:
    shipment_id: int
    order_id: Optional[int]
    status: Optional[str]
    substatus: Optional[str]
    logistic_type: Optional[str]
    tracking_number: Optional[str]
    tracking_method: Optional[str]
    date_created: Optional[datetime]
    last_updated: Optional[datetime]
    receiver_address: Optional[Dict[str, Any]]
    raw_shipment: Dict[str, Any] = field(default_factory=dict)


def _parse_tz_aware(value: Any) -> Optional[datetime]:
    """Parses an ML ISO timestamp string to a tz-aware `datetime` (UTC-
    comparable). Naive results (should not happen with real ML payloads,
    which always carry an offset) are defensively assumed UTC rather than
    silently compared as naive. Returns None for None/empty input; raises
    `ValueError` for an unparseable non-empty string — the caller
    (`map_order`/`map_shipment`) turns that into a `MappingError`.
    """
    if value is None or value == "":
        return None

    parsed = isoparse(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _map_item(raw_item: Dict[str, Any]) -> OrderItemOpsDTO:
    item = raw_item.get("item") or {}
    return OrderItemOpsDTO(
        item_id=str(item.get("id")),
        variation_id=item.get("variation_id"),
        seller_sku=item.get("seller_sku"),
        title=item.get("title"),
        quantity=raw_item.get("quantity"),
        unit_price=raw_item.get("unit_price"),
        full_unit_price=raw_item.get("full_unit_price"),
        sale_fee=raw_item.get("sale_fee"),
        listing_type_id=raw_item.get("listing_type_id"),
        raw_item=raw_item,
    )


def map_order(payload: Dict[str, Any]) -> Union[OrderOpsDTO, MappingError]:
    """Maps a raw ML `/orders/{id}` payload to `OrderOpsDTO`.

    Required (fail-closed if missing/unparseable): `id`, `seller.id`,
    `date_last_updated`. Everything else is optional and defaults to
    None/empty so a payload with only the required fields still maps.
    """
    if not payload:
        return MappingError("empty payload", payload)

    raw_id = payload.get("id")
    if raw_id is None:
        return MappingError("missing required field: id", payload)
    try:
        order_id = int(raw_id)
    except (TypeError, ValueError):
        return MappingError(f"unparseable order id: {raw_id!r}", payload)

    seller = payload.get("seller") or {}
    raw_seller_id = seller.get("id")
    if raw_seller_id is None:
        return MappingError("missing required field: seller.id", payload)
    try:
        seller_id = int(raw_seller_id)
    except (TypeError, ValueError):
        return MappingError(f"unparseable seller id: {raw_seller_id!r}", payload)

    raw_last_updated = payload.get("date_last_updated")
    if raw_last_updated is None:
        return MappingError("missing required field: date_last_updated", payload)
    try:
        ml_last_updated = _parse_tz_aware(raw_last_updated)
    except (ValueError, OverflowError) as e:
        return MappingError(f"unparseable date_last_updated: {raw_last_updated!r} ({e})", payload)

    try:
        date_created = _parse_tz_aware(payload.get("date_created"))
        date_closed = _parse_tz_aware(payload.get("date_closed"))
    except (ValueError, OverflowError) as e:
        return MappingError(f"unparseable order timestamp: {e}", payload)

    buyer = payload.get("buyer") or {}
    shipping = payload.get("shipping") or {}
    raw_shipping_id = shipping.get("id")
    try:
        shipping_id = int(raw_shipping_id) if raw_shipping_id is not None else None
    except (AttributeError, TypeError, ValueError):
        return MappingError(f"unparseable shipping id: {raw_shipping_id!r}", payload)

    try:
        items = [_map_item(raw_item) for raw_item in (payload.get("order_items") or [])]
    except (AttributeError, TypeError, ValueError) as e:
        return MappingError(f"unparseable order_items: {e}", payload)

    return OrderOpsDTO(
        order_id=order_id,
        seller_id=seller_id,
        ml_last_updated=ml_last_updated,  # type: ignore[arg-type]
        pack_id=payload.get("pack_id"),
        status=payload.get("status"),
        status_detail=payload.get("status_detail"),
        date_created=date_created,
        date_closed=date_closed,
        buyer_id=buyer.get("id"),
        buyer_nickname=buyer.get("nickname"),
        total_amount=payload.get("total_amount"),
        paid_amount=payload.get("paid_amount"),
        currency_id=payload.get("currency_id"),
        shipping_id=shipping_id,
        tags=payload.get("tags") or [],
        raw_order=payload,
        items=items,
    )


def map_shipment(payload: Dict[str, Any]) -> Union[ShipmentOpsDTO, MappingError]:
    """Maps a raw ML `/shipments/{id}` payload to `ShipmentOpsDTO`.

    Required (fail-closed if missing/unparseable): `id`.
    """
    if not payload:
        return MappingError("empty payload", payload)

    raw_id = payload.get("id")
    if raw_id is None:
        return MappingError("missing required field: id", payload)
    try:
        shipment_id = int(raw_id)
    except (TypeError, ValueError):
        return MappingError(f"unparseable shipment id: {raw_id!r}", payload)

    raw_order_id = payload.get("order_id")
    try:
        order_id = int(raw_order_id) if raw_order_id is not None else None
    except (TypeError, ValueError):
        return MappingError(f"unparseable order_id: {raw_order_id!r}", payload)

    try:
        date_created = _parse_tz_aware(payload.get("date_created"))
        last_updated = _parse_tz_aware(payload.get("last_updated"))
    except (ValueError, OverflowError) as e:
        return MappingError(f"unparseable shipment timestamp: {e}", payload)

    return ShipmentOpsDTO(
        shipment_id=shipment_id,
        order_id=order_id,
        status=payload.get("status"),
        substatus=payload.get("substatus"),
        logistic_type=payload.get("logistic_type"),
        tracking_number=payload.get("tracking_number"),
        tracking_method=payload.get("tracking_method"),
        date_created=date_created,
        last_updated=last_updated,
        receiver_address=payload.get("receiver_address"),
        raw_shipment=payload,
    )
