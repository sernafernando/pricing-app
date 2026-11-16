"""Shared helpers for the Tienda Nube catalog writers.

`tienda_nube_productos` has TWO writers: the worker handler `tienda_nube.sync`
(`app/workers/handlers/tienda_nube_sync.py`, every 15 minutes in business hours; it replaced the cron script
`scripts/sync_tienda_nube.py`), which runs `sincronizar_catalogo`, and `POST /api/tienda-nube/sync`
(`app/api/endpoints/tienda_nube.py`). Both must map TN's product-level `published` boolean onto every per-variant row
identically, store the same texts (`guardar_textos`) and apply the manual links last (`aplicar_vinculos_manuales`).
"""

import re
from html.parser import HTMLParser
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

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


# --- TN texts (abm-productos S12) -------------------------------------------------------------------------------

# Tags that end a line of the plain text. `li` also starts one, with "- ".
_BLOCK_TAGS = frozenset(
    "p div br h1 h2 h3 h4 h5 h6 li ul ol tr table section article blockquote hr pre header footer".split()
)
# An empty one of these (or a `br` on an empty line) is a deliberate blank line.
_SPACER_TAGS = frozenset({"p", "div", "br"})
_SKIPPED_TAGS = frozenset({"script", "style"})


class _TextoPlano(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buffer: list[str] = []
        self._prefix = ""
        self._skipping = 0

    def _flush(self, spacer: bool) -> None:
        line = " ".join("".join(self._buffer).replace("\xa0", " ").split())
        self._buffer = []
        if line:
            self.lines.append(self._prefix + line)
        elif spacer:
            self.lines.append("")
        self._prefix = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipping += 1
        elif tag in _BLOCK_TAGS:
            self._flush(spacer=tag == "br")
            if tag == "li":
                self._prefix = "- "

    def handle_endtag(self, tag: str) -> None:
        if tag == "br":  # a void element: `<br/>` reaches here right after its start tag, which already broke the line
            return
        if tag in _SKIPPED_TAGS:
            self._skipping = max(0, self._skipping - 1)
        elif tag in _BLOCK_TAGS:
            self._flush(spacer=tag in _SPACER_TAGS)

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self._buffer.append(data)


def html_a_texto(html: Optional[str]) -> str:
    """TN's HTML description as plain text, for MercadoLibre (plain text only): block tags end a line, list items
    start with "- ", entities are decoded, other tags dropped (script/style with their content), spaces collapsed
    inside a line and runs of blank lines collapsed to one."""
    if not html:
        return ""
    parser = _TextoPlano()
    parser.feed(html)
    parser.close()
    parser._flush(spacer=False)
    text_ = "\n".join(parser.lines)
    return re.sub(r"\n{3,}", "\n\n", text_).strip("\n")


def extract_textos(product: dict) -> dict[str, Any]:
    """One TN /products entry as its `tienda_nube_producto_textos` row (Spanish name and description)."""
    descripcion = (product.get("description") or {}).get("es") or None
    return {
        "product_id": product.get("id"),
        "nombre": (product.get("name") or {}).get("es", ""),
        "descripcion_html": descripcion,
        "descripcion_texto": html_a_texto(descripcion),
    }


# Writes only when something changed, so `updated_at` says when TN's text last changed.
UPSERT_TEXTOS_SQL = text("""
    INSERT INTO tienda_nube_producto_textos (product_id, nombre, descripcion_html, descripcion_texto, updated_at)
    VALUES (:product_id, :nombre, :descripcion_html, :descripcion_texto, CURRENT_TIMESTAMP)
    ON CONFLICT (product_id) DO UPDATE SET
        nombre = EXCLUDED.nombre,
        descripcion_html = EXCLUDED.descripcion_html,
        descripcion_texto = EXCLUDED.descripcion_texto,
        updated_at = CURRENT_TIMESTAMP
    WHERE NOT (
        COALESCE(tienda_nube_producto_textos.nombre, '') = COALESCE(EXCLUDED.nombre, '')
        AND COALESCE(tienda_nube_producto_textos.descripcion_html, '') = COALESCE(EXCLUDED.descripcion_html, '')
    )
""")


def guardar_textos(db: Session, products: list[dict]) -> int:
    """Upserts the name and description of every fetched TN product; returns how many products it got."""
    rows = [extract_textos(p) for p in products if p.get("id") is not None]
    if rows:
        db.execute(UPSERT_TEXTOS_SQL, rows)
    return len(rows)


# --- ERP links ---------------------------------------------------------------------------------------------------

# The SKU match of the old cron script, unchanged: exact (re-applied on every run), then without / with a leading 0
# for the variants still unlinked.
_MATCH_SKU_SQL = (
    text("""
        UPDATE tienda_nube_productos tn SET item_id = pe.item_id
        FROM productos_erp pe
        WHERE tn.variant_sku = pe.codigo AND tn.activo = true
          AND tn.variant_sku IS NOT NULL AND tn.variant_sku != ''
    """),
    text("""
        UPDATE tienda_nube_productos tn SET item_id = pe.item_id
        FROM productos_erp pe
        WHERE SUBSTRING(tn.variant_sku, 2) = pe.codigo AND tn.item_id IS NULL AND tn.activo = true
          AND tn.variant_sku LIKE '0%' AND LENGTH(tn.variant_sku) > 1
    """),
    text("""
        UPDATE tienda_nube_productos tn SET item_id = pe.item_id
        FROM productos_erp pe
        WHERE '0' || tn.variant_sku = pe.codigo AND tn.item_id IS NULL AND tn.activo = true
          AND tn.variant_sku NOT LIKE '0%' AND tn.variant_sku IS NOT NULL AND tn.variant_sku != ''
    """),
)

# A product linked by hand loses every other TN product the SKU match gave it (all of them when its manual link is
# "not linked"); then the TN product linked by hand gets the product on all its variants. Portable SQL: the manual
# sync endpoint runs it on SQLite in tests.
_VINCULOS_MANUALES_SQL = (
    text("""
        UPDATE tienda_nube_productos SET item_id = NULL
        WHERE EXISTS (
            SELECT 1 FROM producto_tn_vinculos v
            WHERE v.item_id = tienda_nube_productos.item_id
              AND (v.tn_product_id IS NULL OR v.tn_product_id <> tienda_nube_productos.product_id)
        )
    """),
    text("""
        UPDATE tienda_nube_productos
        SET item_id = (SELECT v.item_id FROM producto_tn_vinculos v WHERE v.tn_product_id = tienda_nube_productos.product_id)
        WHERE EXISTS (
            SELECT 1 FROM producto_tn_vinculos v
            WHERE v.tn_product_id = tienda_nube_productos.product_id
              AND (tienda_nube_productos.item_id IS NULL OR tienda_nube_productos.item_id <> v.item_id)
        )
    """),
)


def vincular_por_sku(db: Session) -> None:
    for statement in _MATCH_SKU_SQL:
        db.execute(statement)


def aplicar_vinculos_manuales(db: Session) -> None:
    """Applies `producto_tn_vinculos` over whatever the SKU match left. Runs last in every sync, so a manual link
    always wins, and right after a link is changed by hand, so it shows at once."""
    for statement in _VINCULOS_MANUALES_SQL:
        db.execute(statement)


def sincronizar_catalogo(db: Session, products: list[dict], *, fetch_complete: bool) -> dict[str, int]:
    """One sync pass over the fetched TN catalog, in the caller's transaction (the caller commits).

    Only a COMPLETE fetch marks as inactive the variants TN no longer has; a partial one (an error mid-pagination)
    updates what it brought and leaves the rest alone. Then the texts, the SKU match and the manual links, in that
    order."""
    variantes = [v for product in products for v in extract_variantes(product)]
    if fetch_complete:
        db.execute(text("UPDATE tienda_nube_productos SET activo = false"))
    if variantes:
        db.execute(UPSERT_VARIANTES_SQL, variantes)
    textos = guardar_textos(db, products)
    vincular_por_sku(db)
    aplicar_vinculos_manuales(db)
    stats = db.execute(
        text("""
        SELECT COUNT(*) FILTER (WHERE activo = true),
               COUNT(*) FILTER (WHERE activo = false),
               COUNT(*) FILTER (WHERE item_id IS NOT NULL AND activo = true)
        FROM tienda_nube_productos
    """)
    ).one()
    return {
        "productos": len(products),
        "variantes": len(variantes),
        "activos": stats[0],
        "inactivos": stats[1],
        "con_erp": stats[2],
        "textos": textos,
    }
