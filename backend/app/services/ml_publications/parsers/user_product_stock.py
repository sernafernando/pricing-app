"""`GET /user-products/{id}/stock` (captured 2026-10-06).

Body: `{id, user_id, locations: [{type: selling_address|meli_facility, quantity}], last_updated,
available_sites, product_release_date, stock_mode}`. The typed total is the sum of
`locations[].quantity` (MLAU266459622: 26 + 0 = 26). The key (`id`) comes from the request.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.services.ml_publications.mappers import to_timestamp
from app.services.ml_publications.parsers.subresource import (
    MalformedSubResource,
    ParsedSubResource,
    parse_subresource,
    require_object,
)


def _validate(body: Any) -> None:
    obj = require_object(body, "user_product_stock")
    if not isinstance(obj.get("id"), str) or not isinstance(obj.get("locations"), list):
        raise MalformedSubResource("user_product_stock: `id` (string) and `locations` (list) are required")


def parse_user_product_stock(status: int, body: Any) -> ParsedSubResource:
    return parse_subresource(status, body, _validate)


def map_user_product_stock(raw: Mapping[str, Any]) -> dict[str, Any]:
    locations = raw.get("locations")
    total: Optional[int] = None
    if isinstance(locations, list):
        total = sum(
            loc["quantity"]
            for loc in locations
            if isinstance(loc, Mapping)
            and isinstance(loc.get("quantity"), int)
            and not isinstance(loc["quantity"], bool)
        )
    return {"total_quantity": total, "ml_last_updated": to_timestamp(raw.get("last_updated"))}
