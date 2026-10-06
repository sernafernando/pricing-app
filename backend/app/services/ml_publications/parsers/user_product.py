"""`GET /user-products/{id}` (captured 2026-10-06).

Body (relevant part): `{id: "MLAU...", name, family_name, family_id, domain_id, catalog_product_id,
site_id, user_id, attributes, pictures, last_updated (+0000 offset), ...}`. `family_id` is typed as
an exact integer (the captured values exceed 2**52). The key (`id`) comes from the request.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ml_publications.mappers import to_timestamp
from app.services.ml_publications.parsers.subresource import (
    MalformedSubResource,
    ParsedSubResource,
    parse_subresource,
    require_object,
)


def _validate(body: Any) -> None:
    obj = require_object(body, "user_product")
    if not isinstance(obj.get("id"), str):
        raise MalformedSubResource("user_product: `id` must be a string")


def parse_user_product(status: int, body: Any) -> ParsedSubResource:
    return parse_subresource(status, body, _validate)


def map_user_product(raw: Mapping[str, Any]) -> dict[str, Any]:
    family_id = raw.get("family_id")
    return {
        "family_id": family_id if isinstance(family_id, int) and not isinstance(family_id, bool) else None,
        "name": raw.get("name"),
        "domain_id": raw.get("domain_id"),
        "catalog_product_id": raw.get("catalog_product_id"),
        "ml_last_updated": to_timestamp(raw.get("last_updated")),
    }
