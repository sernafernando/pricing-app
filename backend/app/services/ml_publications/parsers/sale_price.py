"""`GET /items/{id}/sale_price?context=channel_marketplace` (captured 2026-10-06).

Body: `{price_id, amount, regular_amount, currency_id, reference_date, metadata}` where `metadata`
is `{}` without a promotion and `{campaign_id, promotion_id, promotion_type}` with one.

`reference_date` is the response time (it equals the `Date` header of every capture), so it moves
on every fetch without any state change. It is NOT typed; it stays in raw. The diff engine ignores it
(`EXCLUDED_NOISE[("sale_price", "reference_date")]`, justified there), so a fetch that only moves it
refreshes raw but writes no change-log row.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ml_publications.mappers import to_decimal
from app.services.ml_publications.parsers.subresource import (
    MalformedSubResource,
    ParsedSubResource,
    parse_subresource,
    require_object,
)


def _validate(body: Any) -> None:
    obj = require_object(body, "sale_price")
    if "amount" not in obj:
        raise MalformedSubResource("sale_price: `amount` missing")


def parse_sale_price(status: int, body: Any) -> ParsedSubResource:
    return parse_subresource(status, body, _validate)


def map_sale_price(raw: Mapping[str, Any]) -> dict[str, Any]:
    metadata = raw.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    price_id = raw.get("price_id")
    return {
        "price_id": None if price_id is None else str(price_id),
        "amount": to_decimal(raw.get("amount")),
        "regular_amount": to_decimal(raw.get("regular_amount")),
        "currency_id": raw.get("currency_id"),
        "campaign_id": metadata.get("campaign_id"),
        "promotion_id": metadata.get("promotion_id"),
        "promotion_type": metadata.get("promotion_type"),
    }
