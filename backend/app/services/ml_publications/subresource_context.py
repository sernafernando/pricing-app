"""Derivation context of the price sub-resources (design D8, D16).

A change-log row stores, besides its changed paths, the minimal inputs the event rules need so
events can be re-derived from the row alone. For `prices` and `sale_price` that is the entries
the business reads, before and after the change, with amounts as decimal strings:

    {"entries": {"old": <entries or None>, "new": <entries or None>}}

`prices` entries: `{"standard": {amount, currency_id, price_id} | None,
"promotion": {amount, price_id, promotion_id, promotion_type} | None}`, selected for the
marketplace channel exactly as the typed columns are. `sale_price` entries: `{amount,
regular_amount, currency_id, campaign_id, promotion_id, promotion_type}`. `promotions` entries: the
list keyed by promotion key (`id`, else `type`), each `{id, type, status, price, original_price,
min/max/suggested_discounted_price}` with amounts as decimal strings; a key ML repeats is
`{ambiguous: true, id, type}` and raises no event. No I/O.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Mapping, Optional

from app.services.ml_publications.mappers import to_decimal
from app.services.ml_publications.parsers.prices import marketplace_entries
from app.services.ml_publications.parsers.sale_price import map_sale_price
from app.services.ml_publications.parsers.seller_promotions import promotion_key
from app.services.ml_publications.resources import PROMOTIONS_RESOURCE

PRICES = "prices"
SALE_PRICE = "sale_price"
PROMOTIONS = PROMOTIONS_RESOURCE


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


_PROMOTION_AMOUNTS = (
    "price",
    "original_price",
    "min_discounted_price",
    "max_discounted_price",
    "suggested_discounted_price",
)


def _amount_of(entry: Mapping[str, Any], name: str) -> Optional[str]:
    return _money(to_decimal(entry.get(name)))


def promotions_entries(raw: Any) -> Optional[dict]:
    """The promotions the event rules read, by promotion key (`id`, else `type`).

    ML sends one entry per key. If a key ever repeats, its entries cannot be told apart across two
    fetches (nothing says which twin is which), so the key is kept as `{"ambiguous": True, id, type}`
    and the event rules skip it: no event is better than an event that may be false."""
    if not isinstance(raw, list):
        return None
    entries: dict = {}
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        key = promotion_key(entry)
        identity = {"id": None if entry.get("id") is None else str(entry["id"]), "type": entry.get("type")}
        if key in entries:  # a repeat (third and later ones too): the key stays ambiguous
            entries[key] = {"ambiguous": True, **identity}
        else:
            entries[key] = {
                **identity,
                "status": entry.get("status"),
                **{name: _amount_of(entry, name) for name in _PROMOTION_AMOUNTS},
            }
    return entries


_BUILDERS: dict[str, Callable[[Any], Optional[dict]]] = {
    PRICES: prices_entries,
    SALE_PRICE: sale_price_entries,
    PROMOTIONS: promotions_entries,
}


def entries_context(resource: str, old_raw: Any, new_raw: Any) -> dict:
    """The `entries` context of a change of `resource`; empty for resources with no event rules yet."""
    build = _BUILDERS.get(resource)
    if build is None:
        return {}
    return {"entries": {"old": build(old_raw), "new": build(new_raw)}}
