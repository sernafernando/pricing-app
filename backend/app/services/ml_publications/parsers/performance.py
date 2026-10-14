"""`GET /item/{id}/performance` (captured 2026-10-06; note `item`, singular).

200 body: `{entity_type: "USER_PRODUCT", entity_id: "MLAU...", score, level, calculated_at, buckets[]}`.
Performance is reported per user product, so items sharing one return the same body.

ML answers `400 {error: "bad_request", status: 400, message: "Entity not calculated: <reason>"}` when it
computes no performance for the item. Each captured reason is a state (`applicable = false`, the reason kept
in the stored raw), not an error, so the queue entry completes without a charged attempt:

- "Product items are not supported": a catalog product item (captured 2026-10-06);
- "Only status active is supported": a paused, closed or under-review item (prod, 2026-10-14);
- "Item does not have marketplace channel": an item not listed on the marketplace (prod, 2026-10-14).

Only those captured reasons are the state: any other 400 stays an error, so a different refusal is never
recorded as "not applicable". A non-active item is answered again once it is active (sweeps recheck a stored
"not applicable" at the long interval).
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ml_publications.mappers import to_decimal, to_timestamp
from app.services.ml_publications.parsers.subresource import (
    ParsedSubResource,
    parse_subresource,
    require_object,
)

NOT_APPLICABLE_STATUS = 400
NOT_APPLICABLE_MESSAGES = frozenset(
    {
        "Entity not calculated: Product items are not supported",
        "Entity not calculated: Only status active is supported",
        "Entity not calculated: Item does not have marketplace channel",
    }
)
# HTTP status -> state name, as registered in `ResourceSpec.negative_states`.
NEGATIVE_STATES = {NOT_APPLICABLE_STATUS: "not_applicable"}


def is_not_applicable(body: Any) -> bool:
    return isinstance(body, Mapping) and body.get("message") in NOT_APPLICABLE_MESSAGES


def _validate(body: Any) -> None:
    require_object(body, "performance")


def parse_performance(status: int, body: Any) -> ParsedSubResource:
    if status == NOT_APPLICABLE_STATUS and is_not_applicable(body):
        return ParsedSubResource(status=status, state="ok", body=body)
    return parse_subresource(status, body, _validate)


def map_performance(raw: Mapping[str, Any]) -> dict[str, Any]:
    if is_not_applicable(raw):
        return {
            "applicable": False,
            "entity_type": None,
            "entity_id": None,
            "score": None,
            "level": None,
            "calculated_at": None,
        }
    return {
        "applicable": True,
        "entity_type": raw.get("entity_type"),
        "entity_id": raw.get("entity_id"),
        "score": to_decimal(raw.get("score")),
        "level": raw.get("level"),
        "calculated_at": to_timestamp(raw.get("calculated_at")),
    }
