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


FULL_LOCATION = "meli_facility"
OWN_LOCATIONS = frozenset({"selling_address", "seller_warehouse"})


def _validate(body: Any) -> None:
    obj = require_object(body, "user_product_stock")
    if not isinstance(obj.get("id"), str) or not isinstance(obj.get("locations"), list):
        raise MalformedSubResource("user_product_stock: `id` (string) and `locations` (list) are required")


def parse_user_product_stock(status: int, body: Any) -> ParsedSubResource:
    return parse_subresource(status, body, _validate)


def _quantity(loc: Any) -> Optional[int]:
    if isinstance(loc, Mapping) and isinstance(loc.get("quantity"), int) and not isinstance(loc["quantity"], bool):
        return loc["quantity"]
    return None


def map_user_product_stock(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Typed total plus the per-location split.

    `full_quantity` is the `meli_facility` quantity (Full); `own_quantity` adds `selling_address` and
    `seller_warehouse` (the seller's own stock). Flex is not a stock location in MercadoLibre. When
    `locations` is a valid list a type that is absent counts 0; when it is not a list the split is NULL.
    """
    locations = raw.get("locations")
    total: Optional[int] = None
    full: Optional[int] = None
    own: Optional[int] = None
    if isinstance(locations, list):
        total = sum(q for q in map(_quantity, locations) if q is not None)
        full = own = 0
        for loc in locations:
            quantity = _quantity(loc)
            if quantity is None:
                continue
            if loc.get("type") == FULL_LOCATION:
                full += quantity
            elif loc.get("type") in OWN_LOCATIONS:
                own += quantity
    return {
        "total_quantity": total,
        "full_quantity": full,
        "own_quantity": own,
        "ml_last_updated": to_timestamp(raw.get("last_updated")),
    }
