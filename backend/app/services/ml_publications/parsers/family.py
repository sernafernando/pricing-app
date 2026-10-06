"""`GET /sites/MLA/user-products-families/{family_id}` (captured 2026-10-06).

Body: `{user_products_ids: ["MLAU..."], family_id, site_id, user_id}`. `family_id` is the key (BIGINT,
exact: the captured values exceed 2**52) and comes from the request; the parser checks the body
carries it as an integer. The typed column is the list of user products of the family.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ml_publications.parsers.subresource import (
    MalformedSubResource,
    ParsedSubResource,
    parse_subresource,
    require_object,
)


def _validate(body: Any) -> None:
    obj = require_object(body, "family")
    family_id = obj.get("family_id")
    if not isinstance(family_id, int) or isinstance(family_id, bool):
        raise MalformedSubResource("family: `family_id` must be an integer")
    ids = obj.get("user_products_ids")
    if not isinstance(ids, list) or not all(isinstance(value, str) for value in ids):
        raise MalformedSubResource("family: `user_products_ids` must be a list of strings")


def parse_family(status: int, body: Any) -> ParsedSubResource:
    return parse_subresource(status, body, _validate)


def map_family(raw: Mapping[str, Any]) -> dict[str, Any]:
    ids = raw.get("user_products_ids")
    return {"user_products_ids": [value for value in ids if isinstance(value, str)] if isinstance(ids, list) else None}
