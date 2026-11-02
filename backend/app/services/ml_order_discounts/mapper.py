"""Pure mapping of `GET /orders/{order_id}/discounts` (captured 2026-11-02, `tests/fixtures/ml_order_discounts`).

Body: `{details: [{type, coupon?: {id}, supplier: {campaign_id?, meli_campaign?, funding_mode?, offer_id?},
items: [{id, element_id, quantity, amounts: {seller, total}}]}]}`. A sale with no discounts answers 404
`{error: "discount_not_found", status: 404}`. The body's own `status` wins over the HTTP one, since a proxy can
answer 200 around an ML error. Nothing here does I/O or raises on an unexpected shape: an unknown field is
ignored and a missing one maps to None (the whole body is stored anyway).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional

OK = "ok"
NONE = "none"
ERROR = "error"
NOT_FOUND_ERROR = "discount_not_found"  # the only 404 that means "this sale has no discounts"


@dataclass(frozen=True)
class DiscountLine:
    order_id: int
    detail_index: int
    item_index: int
    type: Optional[str]
    coupon_id: Optional[int]
    campaign_id: Optional[int]
    meli_campaign: Optional[str]
    offer_id: Optional[str]
    funding_mode: Optional[str]
    item_id: Optional[str]
    element_id: Optional[int]
    quantity: Optional[int]
    amount_seller: Optional[Decimal]
    amount_total: Optional[Decimal]


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _money(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None  # NaN / Infinity (Python's json accepts them) would raise on quantize
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def body_status(http_status: int, body: Any) -> int:
    """ML's own status: an error body's numeric `status` when it has one, else the HTTP status."""
    own = _int(_mapping(body).get("status"))
    return own if own is not None and own >= 400 else http_status


def classify(http_status: int, body: Any) -> str:
    """`ok` for a readable body, `none` for ML's "Discount not found" 404 (any other 404 is an error, so a sale is
    never settled as discount-free by an unrelated not-found), `error` for anything else."""
    status = body_status(http_status, body)
    if status == 404:
        return NONE if _mapping(body).get("error") == NOT_FOUND_ERROR else ERROR
    if 200 <= status < 300 and isinstance(_mapping(body).get("details"), list):
        return OK
    return ERROR


def map_lines(order_id: int, body: Any) -> list[DiscountLine]:
    lines = []
    for detail_index, detail in enumerate(_mapping(body).get("details") or []):
        if not isinstance(detail, Mapping):
            continue
        coupon, supplier = _mapping(detail.get("coupon")), _mapping(detail.get("supplier"))
        items = detail.get("items") if isinstance(detail.get("items"), list) else []
        for item_index, item in enumerate(items):
            if not isinstance(item, Mapping):
                continue
            amounts = _mapping(item.get("amounts"))
            lines.append(
                DiscountLine(
                    order_id=order_id,
                    detail_index=detail_index,
                    item_index=item_index,
                    type=_text(detail.get("type")),
                    coupon_id=_int(coupon.get("id")),
                    campaign_id=_int(supplier.get("campaign_id")),
                    meli_campaign=_text(supplier.get("meli_campaign")),
                    offer_id=_text(supplier.get("offer_id")),
                    funding_mode=_text(supplier.get("funding_mode")),
                    item_id=_text(item.get("id")),
                    element_id=_int(item.get("element_id")),
                    quantity=_int(item.get("quantity")),
                    amount_seller=_money(amounts.get("seller")),
                    amount_total=_money(amounts.get("total")),
                )
            )
    return lines
