"""v1 TN payload assembly (PC7 visibility, PC9 inventory_levels, D1/D4).

`assemble_payload` is the ONLY place in this change that builds a TN
product-create body's measurement/stock fragment — never hand-rolled
inline at a call site, so PC7/PC9 stay structurally true instead of
discipline-dependent.
"""

from typing import Any, Dict, List, Optional

from app.services.tn_publish_core.resolve import Resolved


def assemble_payload(
    resolved_fields: Dict[str, Resolved],
    *,
    name_es: str,
    price: str,
    stock: Optional[int] = None,
    category_id: int,
    visibility: str = "visible",
    free_shipping: bool = False,
    seo_title: Optional[str] = None,
    seo_description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    description_html: str = "",
    sku: Optional[str] = None,
    barcode: Optional[str] = None,
    cost: Optional[float] = None,
    promotional_price: Optional[str] = None,
) -> Dict[str, Any]:
    """Builds a TN v1 product-create payload from precedence-resolved
    fields.

    PC7/D4: the payload carries `visibility` (`visible`/`unlisted`/
    `hidden`), NEVER `published` — that key is a stale v0-era concept this
    module must never emit.

    PC9/D1: stock is transmitted as `variants[0]["inventory_levels"] =
    [{"stock": N}]`; NO top-level `variant["stock"]` key is ever set — TN
    v1 has no such field, and a legacy `stock` key would simply be ignored
    by TN with no error, silently losing the operator's stock value.

    `stock=None` (genuinely absent — never coerced from a caller's `""`/
    junk value, that coercion is the caller's job): `inventory_levels` is
    OMITTED entirely, never fabricated as `[{"stock": 0}]`. TN then applies
    its own product-create default rather than this module inventing a
    number the operator never provided — the same "absence over a
    fabricated number" discipline `_upsert_publish_mirror` already applies
    to `variant_id`.
    """
    variant: Dict[str, Any] = {
        "price": price,
        "weight": resolved_fields["weight"].value,
        "width": resolved_fields["width"].value,
        "depth": resolved_fields["depth"].value,
        "height": resolved_fields["height"].value,
    }
    if stock is not None:
        variant["inventory_levels"] = [{"stock": stock}]
    if sku is not None:
        variant["sku"] = sku
    # TN v1 keeps these on the VARIANT, not the product root — an operator
    # edit landing at the root is silently dropped by TN, which is the same
    # class of loss `inventory_levels` guards against above. Only keys the
    # operator actually supplied are emitted; absence stays absence.
    if barcode is not None:
        variant["barcode"] = barcode
    if cost is not None:
        variant["cost"] = cost
    if promotional_price is not None:
        variant["promotional_price"] = promotional_price

    payload: Dict[str, Any] = {
        "name": {"es": name_es},
        "categories": [category_id],
        "visibility": visibility,
        "free_shipping": free_shipping,
        "description": {"es": description_html},
        "tags": tags or [],
        "variants": [variant],
    }
    if seo_title is not None:
        payload["seo_title"] = {"es": seo_title}
    if seo_description is not None:
        payload["seo_description"] = {"es": seo_description}
    return payload
