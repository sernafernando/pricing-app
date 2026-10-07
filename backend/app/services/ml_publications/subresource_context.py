"""Derivation context of the price sub-resources (design D8, D16).

A change-log row stores, besides its changed paths, the minimal inputs the event rules need so
events can be re-derived from the row alone. For `prices` and `sale_price` that is the entries
the business reads, before and after the change, with amounts as decimal strings:

    {"entries": {"old": <entries or None>, "new": <entries or None>}}

`prices` entries: `{"standard": {amount, currency_id, price_id} | None,
"promotion": {amount, price_id, promotion_id, promotion_type} | None}`, selected for the
marketplace channel exactly as the typed columns are. `sale_price` entries: `{amount,
regular_amount, currency_id, campaign_id, promotion_id, promotion_type}`. No I/O.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Mapping, Optional

from app.services.ml_publications.mappers import to_decimal
from app.services.ml_publications.parsers.prices import marketplace_entries
from app.services.ml_publications.parsers.sale_price import map_sale_price

PRICES = "prices"
SALE_PRICE = "sale_price"


def _money(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


def _amount(entry: Mapping[str, Any]) -> Optional[str]:
    return _money(to_decimal(entry.get("amount")))


def _price_id(entry: Mapping[str, Any]) -> Optional[str]:
    price_id = entry.get("id")
    return None if price_id is None else str(price_id)


def prices_entries(raw: Any) -> Optional[dict]:
    if not isinstance(raw, Mapping):
        return None
    standard, promotion = marketplace_entries(raw)
    metadata = promotion.get("metadata") if promotion else None
    metadata = metadata if isinstance(metadata, Mapping) else {}
    return {
        "standard": None
        if standard is None
        else {"amount": _amount(standard), "currency_id": standard.get("currency_id"), "price_id": _price_id(standard)},
        "promotion": None
        if promotion is None
        else {
            "amount": _amount(promotion),
            "price_id": _price_id(promotion),
            "promotion_id": metadata.get("promotion_id"),
            "promotion_type": metadata.get("promotion_type"),
        },
    }


def sale_price_entries(raw: Any) -> Optional[dict]:
    if not isinstance(raw, Mapping):
        return None
    typed = map_sale_price(raw)
    return {
        "amount": _money(typed["amount"]),
        "regular_amount": _money(typed["regular_amount"]),
        "currency_id": typed["currency_id"],
        "campaign_id": typed["campaign_id"],
        "promotion_id": typed["promotion_id"],
        "promotion_type": typed["promotion_type"],
    }


_BUILDERS: dict[str, Callable[[Any], Optional[dict]]] = {PRICES: prices_entries, SALE_PRICE: sale_price_entries}


def entries_context(resource: str, old_raw: Any, new_raw: Any) -> dict:
    """The `entries` context of a change of `resource`; empty for resources with no event rules yet."""
    build = _BUILDERS.get(resource)
    if build is None:
        return {}
    return {"entries": {"old": build(old_raw), "new": build(new_raw)}}
