"""Product links: publication units <-> our products by SKU (design D20, spec Domain 6).

A link unit is `(item_id, variation_id)`; `variation_id = 0` is the item-level unit of an item
without variations. The automatic rule matches the unit's SKU key against `ProductoERP.codigo`
with the same precedence and equality the orders use (SELLER_SKU attribute, else
`seller_custom_field`; exact string equality, no normalization). A manual decision always wins:
the automatic path only refreshes its suggestion columns.

This is the only module of the package that reads `ProductoERP`, and it writes only the link
table, the change log (resource `product_link`) and the events derived from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

SKU_FIELD_ATTRIBUTE = "seller_sku_attr"
SKU_FIELD_CUSTOM = "seller_custom_field"

ITEM_LEVEL = 0  # `variation_id` of the item-level unit

STATUS_LINKED = "linked"
STATUS_UNMATCHED = "unmatched"
STATUS_CONFLICT = "conflict"


@dataclass(frozen=True)
class LinkUnit:
    """One unit and its SKU key (None when ML carries no usable SKU for it)."""

    item_id: str
    variation_id: int
    key: Optional[str]
    sku_field: Optional[str]


@dataclass(frozen=True)
class Suggestion:
    """What the automatic rule says about a unit, whatever its current link is."""

    status: str  # linked | unmatched | conflict
    producto_item_id: Optional[int]
    matched_sku: Optional[str]
    sku_field: Optional[str]
    candidates: tuple[int, ...]  # every product holding the key's `codigo` (sorted, distinct)


def _usable(value: Any) -> Optional[str]:
    """A SKU as ML sent it, or None when absent (missing, not text or empty string)."""
    return value if isinstance(value, str) and value != "" else None


def sku_key(seller_sku: Any, seller_custom_field: Any) -> tuple[Optional[str], Optional[str]]:
    """`(key, sku_field)`: the SELLER_SKU attribute value, else `seller_custom_field`.

    Same precedence as the orders' `seller_sku` linkage; the value is never trimmed or case-folded.
    """
    sku = _usable(seller_sku)
    if sku is not None:
        return sku, SKU_FIELD_ATTRIBUTE
    custom = _usable(seller_custom_field)
    if custom is not None:
        return custom, SKU_FIELD_CUSTOM
    return None, None


def units_for_item(typed_item: Mapping[str, Any], typed_variations: Sequence[Mapping[str, Any]]) -> list[LinkUnit]:
    """The link units of an item from its typed columns (`map_item` / `map_variations` shapes).

    An item with variations has one unit per variation and no item-level unit; a variation
    without a SKU of its own inherits the item's key.
    """
    item_id = typed_item["item_id"]
    item_key, item_field = sku_key(typed_item.get("seller_sku"), typed_item.get("seller_custom_field"))
    units: list[LinkUnit] = []
    seen: set[int] = set()
    for variation in typed_variations:
        variation_id = variation.get("variation_id")
        if not isinstance(variation_id, int) or isinstance(variation_id, bool) or variation_id <= 0:
            continue
        if variation_id in seen:
            continue
        seen.add(variation_id)
        key, field = sku_key(variation.get("seller_sku"), variation.get("seller_custom_field"))
        if key is None:
            key, field = item_key, item_field
        units.append(LinkUnit(item_id, variation_id, key, field))
    if not units:
        units.append(LinkUnit(item_id, ITEM_LEVEL, item_key, item_field))
    return units


def keys_of(units: Sequence[LinkUnit]) -> list[str]:
    """The distinct SKU keys to look up in the product catalog, sorted."""
    return sorted({unit.key for unit in units if unit.key is not None})


def resolve(unit: LinkUnit, codigo_index: Mapping[str, Sequence[int]]) -> Suggestion:
    """Pure rule: one product with that `codigo` links, none is unmatched, several conflict."""
    if unit.key is None:
        return Suggestion(STATUS_UNMATCHED, None, None, None, ())
    candidates = tuple(sorted(set(codigo_index.get(unit.key, ()))))
    if len(candidates) == 1:
        return Suggestion(STATUS_LINKED, candidates[0], unit.key, unit.sku_field, candidates)
    status = STATUS_CONFLICT if candidates else STATUS_UNMATCHED
    return Suggestion(status, None, unit.key, unit.sku_field, candidates)
