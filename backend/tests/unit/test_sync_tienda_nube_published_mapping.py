"""Unit tests for the TN sync's product->variant `published` mapping
(DESPUBLICAR bugfix).

TN's `published` boolean lives at the PRODUCT level in the /products
response, but `tienda_nube_productos` stores one row per VARIANT — so the
sync must copy the product-level flag onto every variant row it upserts.

Pure-function test: no DB, no httpx — only `_extract_variantes`'s mapping
logic.
"""

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_BACKEND_ROOT))

from scripts.sync_tienda_nube import UPSERT_VARIANTES_SQL, _extract_variantes  # noqa: E402


def _product(product_id=1, published=True, name="Producto", variants=None):
    return {
        "id": product_id,
        "name": {"es": name},
        "published": published,
        "variants": variants if variants is not None else [{"id": 10, "sku": "SKU-1", "price": "100.0"}],
    }


class TestPublishedMapping:
    def test_published_true_copied_to_every_variant(self):
        product = _product(published=True, variants=[{"id": 10, "sku": "A"}, {"id": 11, "sku": "B"}])

        variantes = _extract_variantes(product)

        assert len(variantes) == 2
        assert all(v["published"] is True for v in variantes)

    def test_published_false_copied_to_every_variant(self):
        product = _product(published=False, variants=[{"id": 10, "sku": "A"}])

        variantes = _extract_variantes(product)

        assert len(variantes) == 1
        assert variantes[0]["published"] is False

    def test_missing_published_field_maps_to_none_not_false(self):
        """If TN's API ever omits `published`, the sync must NOT silently
        assume False (which would incorrectly clear a previously-known
        published=True) — map to None (unknown) instead."""
        product = _product()
        del product["published"]

        variantes = _extract_variantes(product)

        assert variantes[0]["published"] is None


class TestUpsertNeverOverwritesKnownTrueWithUnknown:
    """`_extract_variantes` maps a missing field to `None`, but the real
    "never clears a known TRUE" guarantee is enforced by the UPSERT's SQL —
    a plain `published = EXCLUDED.published` would let that `None` overwrite
    a previously-stored `True` as NULL. This must be a `COALESCE` so a NULL
    incoming value keeps the existing stored value instead of blanking it.
    """

    def test_upsert_sql_coalesces_published_against_the_existing_value(self):
        sql_text = str(UPSERT_VARIANTES_SQL)
        assert "COALESCE(EXCLUDED.published, tienda_nube_productos.published)" in sql_text
        # Regression guard: a bare `published = EXCLUDED.published` (no
        # COALESCE) is exactly the bug this test protects against.
        assert "published = EXCLUDED.published" not in sql_text
