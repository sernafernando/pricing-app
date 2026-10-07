"""`GET /items/{id}/prices` (captured 2026-10-06).

Body: `{id, prices: [{id, type: standard|promotion, amount, regular_amount, currency_id,
last_updated, conditions: {context_restrictions, start_time, end_time}}]}`.

An item can carry several standard prices, one per sales channel: MLA874027718 has a
`channel_marketplace` price (55882.0, the one `sale_price?context=channel_marketplace` reports)
and a `channel_mshops` price (39990.0). The typed columns follow the marketplace: an entry
applies when its `context_restrictions` is empty or names `channel_marketplace`, and an explicit
marketplace entry wins over an unrestricted one.

Assumption (pinned by a test over the captures): `/prices` lists only promotions in force, so
`active_promotion_amount` is mapped without reading `conditions.start_time`/`end_time`. If ML ever
returns a scheduled promotion before it starts, the mapper must start checking that window.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional

from app.services.ml_publications.mappers import to_decimal
from app.services.ml_publications.parsers.subresource import (
    MalformedSubResource,
    ParsedSubResource,
    parse_subresource,
    require_object,
)

MARKETPLACE_CONTEXT = "channel_marketplace"


def _validate(body: Any) -> None:
    obj = require_object(body, "prices")
    prices = obj.get("prices")
    if not isinstance(prices, list) or not all(isinstance(entry, dict) for entry in prices):
        raise MalformedSubResource("prices: `prices` must be a list of objects")


def parse_prices(status: int, body: Any) -> ParsedSubResource:
    return parse_subresource(status, body, _validate)


def _restrictions(entry: Mapping[str, Any]) -> list:
    conditions = entry.get("conditions")
    restrictions = conditions.get("context_restrictions") if isinstance(conditions, Mapping) else None
    return restrictions if isinstance(restrictions, list) else []


def _marketplace_entry(prices: list, kind: str) -> Optional[Mapping[str, Any]]:
    """Marketplace-scoped entry of `kind`, else an unrestricted one, else None."""
    unrestricted = None
    for entry in prices:
        if entry.get("type") != kind:
            continue
        restrictions = _restrictions(entry)
        if MARKETPLACE_CONTEXT in restrictions:
            return entry
        if not restrictions and unrestricted is None:
            unrestricted = entry
    return unrestricted


def marketplace_entries(raw: Mapping[str, Any]) -> tuple[Optional[Mapping[str, Any]], Optional[Mapping[str, Any]]]:
    """The marketplace `(standard, promotion)` entries of a prices body (each None when absent)."""
    prices = raw.get("prices")
    entries = [e for e in prices if isinstance(e, Mapping)] if isinstance(prices, list) else []
    return _marketplace_entry(entries, "standard"), _marketplace_entry(entries, "promotion")


def map_prices(raw: Mapping[str, Any]) -> dict[str, Any]:
    standard, promotion = marketplace_entries(raw)
    promotion_amount: Optional[Decimal] = to_decimal(promotion.get("amount")) if promotion else None
    return {
        "standard_amount": to_decimal(standard.get("amount")) if standard else None,
        "currency_id": standard.get("currency_id") if standard else None,
        "active_promotion_amount": promotion_amount,
    }
