"""Raw ML bodies -> typed columns (pure, tolerant of null/missing fields).

Typed values derive only from the ML payload: never from GBP/ERP data. Numeric
ML ids stay exact Python integers; money and health use `Decimal` built from the
JSON text so no binary-float noise reaches `numeric` columns.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional


def _get(mapping: Any, *path: str) -> Any:
    current = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# Public names for the sub-resource mappers (parsers/), which share these conversions.
to_decimal = _decimal
to_timestamp = _timestamp


def attribute_value_name(attributes: Any, attribute_id: str) -> Optional[str]:
    """`value_name` of the attribute `attribute_id`, or None.

    ML leaves `value_id` null for free-text attributes such as SELLER_SKU: the
    value lives in `value_name`.
    """
    if not isinstance(attributes, list):
        return None
    for attribute in attributes:
        if isinstance(attribute, Mapping) and attribute.get("id") == attribute_id:
            value = attribute.get("value_name")
            return value if isinstance(value, str) and value != "" else None
    return None


INSTALLMENTS_CAMPAIGN_TERM = "INSTALLMENTS_CAMPAIGN"


def installments_campaign(sale_terms: Any) -> Optional[str]:
    """`value_name` of the item's `INSTALLMENTS_CAMPAIGN` sale term, or None.

    The markup reads the installments campaign here when the item carries no campaign tag. Same result as the
    JSON path it replaces (`$.sale_terms[*] ? (@.id == "INSTALLMENTS_CAMPAIGN").value_name`, first result, as text):
    the first matching term that HAS a `value_name` decides, a null `value_name` is no campaign, and (lax mode) a
    single term object stands for a one-element list.
    """
    if isinstance(sale_terms, Mapping):
        sale_terms = [sale_terms]
    if not isinstance(sale_terms, list):
        return None
    for term in sale_terms:
        if isinstance(term, Mapping) and term.get("id") == INSTALLMENTS_CAMPAIGN_TERM and "value_name" in term:
            value = term["value_name"]
            return value if value is None or isinstance(value, str) else json.dumps(value)
    return None


def map_item(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Typed columns of an `ml_items` row from one full `/items` body."""
    attributes = raw.get("attributes")
    return {
        "item_id": raw.get("id"),
        "site_id": raw.get("site_id"),
        "seller_id": raw.get("seller_id"),
        "title": raw.get("title"),
        "brand": attribute_value_name(attributes, "BRAND"),
        "family_name": raw.get("family_name"),
        "family_id": raw.get("family_id"),
        "category_id": raw.get("category_id"),
        "domain_id": raw.get("domain_id"),
        "user_product_id": raw.get("user_product_id"),
        "catalog_product_id": raw.get("catalog_product_id"),
        "catalog_listing": raw.get("catalog_listing"),
        "official_store_id": raw.get("official_store_id"),
        "status": raw.get("status"),
        "sub_status": raw.get("sub_status"),
        "tags": raw.get("tags"),
        "installments_campaign": installments_campaign(raw.get("sale_terms")),
        "listing_type_id": raw.get("listing_type_id"),
        "buying_mode": raw.get("buying_mode"),
        "condition": raw.get("condition"),
        "currency_id": raw.get("currency_id"),
        "seller_custom_field": raw.get("seller_custom_field"),
        "seller_sku": attribute_value_name(attributes, "SELLER_SKU"),
        "price": _decimal(raw.get("price")),
        "base_price": _decimal(raw.get("base_price")),
        "original_price": _decimal(raw.get("original_price")),
        "available_quantity": raw.get("available_quantity"),
        "sold_quantity": raw.get("sold_quantity"),
        "initial_quantity": raw.get("initial_quantity"),
        "permalink": raw.get("permalink"),
        "thumbnail": raw.get("thumbnail"),
        "health": _decimal(raw.get("health")),
        "inventory_id": raw.get("inventory_id"),
        "parent_item_id": raw.get("parent_item_id"),
        "shipping_mode": _get(raw, "shipping", "mode"),
        "logistic_type": _get(raw, "shipping", "logistic_type"),
        "free_shipping": _get(raw, "shipping", "free_shipping"),
        "start_time": _timestamp(raw.get("start_time")),
        "stop_time": _timestamp(raw.get("stop_time")),
        "end_time": _timestamp(raw.get("end_time")),
        "expiration_time": _timestamp(raw.get("expiration_time")),
        "date_created": _timestamp(raw.get("date_created")),
        "ml_last_updated": _timestamp(raw.get("last_updated")),
    }


def map_variations(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Typed rows of `ml_item_variations` from an item body (empty when it has none).

    `seller_sku` is read from the variation's own `attributes[].value_name`, which
    the default `/items` shape does not include, so it is NULL there.
    """
    variations = raw.get("variations")
    if not isinstance(variations, list):
        return []
    item_id = raw.get("id")
    rows = []
    for variation in variations:
        if not isinstance(variation, Mapping):
            continue
        rows.append(
            {
                "item_id": item_id,
                "variation_id": variation.get("id"),
                "seller_custom_field": variation.get("seller_custom_field"),
                "seller_sku": attribute_value_name(variation.get("attributes"), "SELLER_SKU"),
                "user_product_id": variation.get("user_product_id"),
                "available_quantity": variation.get("available_quantity"),
                "sold_quantity": variation.get("sold_quantity"),
                "raw": dict(variation),
            }
        )
    return rows
