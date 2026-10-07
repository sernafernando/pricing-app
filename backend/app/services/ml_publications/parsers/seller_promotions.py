"""`GET /seller-promotions/items/{id}?app_version=v2` (captured 2026-10-06).

Body: a JSON list of promotion entries `{id?, type, sub_type?, status: candidate|started, price,
original_price, start_date?, finish_date?, name, min/max/suggested_discounted_price?}`. The
`PRICE_DISCOUNT` entry carries no `id` (one per item), so an entry's natural key is `id`, falling
back to `type` (design D7; same fallback as the bridge mirror). The diff engine keys the list the
same way through `ResourceSpec.array_keys`, so one changed promotion reports only its own paths.

Item-level typed columns are counts and the keys of the started promotions; the entries stay in raw.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.ml_publications.parsers.subresource import (
    MalformedSubResource,
    ParsedSubResource,
    parse_subresource,
)

STATUS_STARTED = "started"
STATUS_CANDIDATE = "candidate"


def _validate(body: Any) -> None:
    if not isinstance(body, list):
        raise MalformedSubResource(f"seller_promotions: expected a JSON list, got {type(body).__name__}")
    for entry in body:
        if not isinstance(entry, dict) or "type" not in entry or "status" not in entry:
            raise MalformedSubResource("seller_promotions: every entry must be an object with `type` and `status`")


def parse_seller_promotions(status: int, body: Any) -> ParsedSubResource:
    return parse_subresource(status, body, _validate)


def promotion_key(entry: Mapping[str, Any]) -> str:
    """Natural key of one entry: `id`, else `type`."""
    value = entry.get("id")
    return str(value) if value is not None else str(entry.get("type"))


def map_seller_promotions(raw: Any) -> dict[str, Any]:
    entries = [e for e in raw if isinstance(e, Mapping)] if isinstance(raw, list) else []
    started = sorted(promotion_key(e) for e in entries if e.get("status") == STATUS_STARTED)
    return {
        "candidate_count": sum(1 for e in entries if e.get("status") == STATUS_CANDIDATE),
        "started_count": len(started),
        "started_promotion_keys": started,
    }
