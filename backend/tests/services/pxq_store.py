"""The store rows a PxQ markup is priced from (S11b): the ML item and its item-level product link.

`resolve_pxq_pricing_context` reads the header's inputs, not `publicaciones_ml`: the list ML charges the item
(`ml_items`) and the product its item-level link points to (`ml_item_product_links`). The SQLite PxQ tests add
both through this helper; which list ML charges is pinned against real Postgres in
`test_pxq_pricing_context_postgres.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.ml_publications import MlItem, MlItemProductLink


def store_rows(mla: str, producto_item_id: int, listing_type_id: str = "gold_special") -> list:
    """The ML item behind `mla` (classic list by default, the list 4 these tests priced before) and its link."""
    return [
        MlItem(item_id=mla, listing_type_id=listing_type_id),
        MlItemProductLink(
            item_id=mla,
            variation_id=0,
            source="sku_auto",
            match_status="linked",
            producto_item_id=producto_item_id,
            linked_at=datetime(2026, 11, 12, tzinfo=timezone.utc),
        ),
    ]
