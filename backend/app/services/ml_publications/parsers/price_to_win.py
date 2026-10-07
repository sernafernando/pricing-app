"""`GET /items/{id}/price_to_win?version=v2` (captured 2026-10-06).

Body: `{item_id, current_price, currency_id, price_to_win, boosts, status, consistent, visit_share,
competitors_sharing_first_place, reason[], catalog_product_id, winner?}`. Two statuses were captured:
`not_listed` (every price field null, `reason: ["item_not_opted_in"]`) and `winning`. The endpoint is
asked only for catalog listings; the other statuses named by the ML documentation (`competing`,
`sharing_first_place`, `listed`) were not captured and are stored as sent. The key comes from the request.
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
    obj = require_object(body, "price_to_win")
    if not isinstance(obj.get("status"), str):
        raise MalformedSubResource("price_to_win: `status` (string) is required")


def parse_price_to_win(status: int, body: Any) -> ParsedSubResource:
    return parse_subresource(status, body, _validate)


def map_price_to_win(raw: Mapping[str, Any]) -> dict[str, Any]:
    consistent = raw.get("consistent")
    return {
        "status": raw.get("status"),
        "price_to_win": to_decimal(raw.get("price_to_win")),
        "current_price": to_decimal(raw.get("current_price")),
        "currency_id": raw.get("currency_id"),
        "consistent": consistent if isinstance(consistent, bool) else None,
    }
