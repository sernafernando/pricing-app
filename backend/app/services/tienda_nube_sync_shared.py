"""Shared, side-effect-free helpers for `tienda_nube_productos` writers.

`tienda_nube_productos` has TWO writers: the cron script
(`scripts/sync_tienda_nube.py`) and `POST /api/tienda-nube/sync`
(`app/api/endpoints/tienda_nube.py`). Both must map TN's product-level
`published` boolean onto every per-variant row identically. This lives in
its own module — not in `scripts/sync_tienda_nube.py` — because that script
has module-level env-var validation that calls `sys.exit(1)` on
misconfiguration; importing it from application code (an endpoint module
loaded at FastAPI startup) would make an app boot crash on a missing env var
that script never needed the app itself to have.
"""

from typing import Optional

from sqlalchemy import text

# Kept here rather than in `scripts/sync_tienda_nube.py` for the same reason as
# the helpers below: importing that script executes its module-level env-var
# guard, which calls `sys.exit(1)`. A test importing it without a `.env` — CI,
# for instance — raises SystemExit during collection and takes down the whole
# pytest run, not just that module.
#
# `published` uses COALESCE deliberately: a plain `EXCLUDED.published` would
# null a previously-known True/False on any sync run whose API response happens
# to omit the field. COALESCE is what actually guarantees "never clear a known
# value with unknown data"; `extract_variantes` alone only guarantees it
# produces `None` instead of `False`. The two work together, and losing either
# one reintroduces the bug.
UPSERT_VARIANTES_SQL = text("""
    INSERT INTO tienda_nube_productos (
        product_id, product_name, variant_id, variant_sku,
        price, compare_at_price, promotional_price, activo, published
    ) VALUES (
        :product_id, :product_name, :variant_id, :variant_sku,
        :price, :compare_at_price, :promotional_price, true, :published
    )
    ON CONFLICT (product_id, variant_id) DO UPDATE SET
        product_name = EXCLUDED.product_name,
        variant_sku = EXCLUDED.variant_sku,
        price = EXCLUDED.price,
        compare_at_price = EXCLUDED.compare_at_price,
        promotional_price = EXCLUDED.promotional_price,
        activo = true,
        published = COALESCE(EXCLUDED.published, tienda_nube_productos.published)
""")


def extract_variantes(product: dict) -> list[dict]:
    """Map one TN /products entry to its per-variant upsert rows.

    TN's `published` boolean lives at the PRODUCT level, but
    `tienda_nube_productos` stores one row per VARIANT, so it's copied onto
    every variant row. Missing/absent `published` maps to `None` (unknown)
    rather than `False` — this function alone does NOT guarantee a known
    `True` survives a sync; that guarantee comes from `UPSERT_VARIANTES_SQL`'s
    `COALESCE`, which keeps the existing stored value whenever the incoming
    one is `None`.
    """
    product_id = product.get("id")
    product_name = product.get("name", {}).get("es", "")
    published = extract_published_flag(product)

    variantes = []
    for variant in product.get("variants", []):
        variant_id = variant.get("id")
        variant_sku = (variant.get("sku") or "").strip()

        price = float(variant.get("price", 0) or 0)
        compare_at_price = variant.get("compare_at_price")
        promotional_price = variant.get("promotional_price")

        if compare_at_price:
            compare_at_price = float(compare_at_price)
        if promotional_price:
            promotional_price = float(promotional_price)

        variantes.append(
            {
                "product_id": product_id,
                "product_name": product_name,
                "variant_id": variant_id,
                "variant_sku": variant_sku,
                "price": price,
                "compare_at_price": compare_at_price,
                "promotional_price": promotional_price,
                "published": published,
            }
        )

    return variantes


def extract_published_flag(product: dict) -> Optional[bool]:
    """Extract TN's product-level `published` flag for one /products entry.

    Missing/absent/non-bool `published` maps to `None` (unknown), never
    `False` — a writer that then blindly overwrites the stored value with
    `False` would silently and incorrectly report a real product as
    unpublished. Both writers additionally protect an existing non-null
    stored value from being nulled by a later `None` (COALESCE in the SQL
    writer, an explicit `if published is not None` guard in the ORM writer)
    — this function only produces the correctly-typed extracted value, it
    does not by itself guarantee that protection.
    """
    published = product.get("published")
    if not isinstance(published, bool):
        return None
    return published
