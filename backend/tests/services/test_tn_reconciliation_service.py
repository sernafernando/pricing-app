"""Unit tests for the TN reconciliation verdict taxonomy (Slice 1, read-only).

These tests cover `compute_verdicts` in isolation: no HTTP, no GBP fetch, no
DB session — only the pure EAN-join + verdict logic. GBP fetch failure
handling (`fetch_gbp_report_78`) is covered separately.
"""

from app.models.tienda_nube_producto import TiendaNubeProducto
from app.services.tn_reconciliation_service import compute_verdicts


def _tn(product_id=1, variant_id=1, sku="EAN-1", activo=True, published=None):
    return TiendaNubeProducto(
        product_id=product_id,
        variant_id=variant_id,
        variant_sku=sku,
        activo=activo,
        published=published,
    )


def _gbp_row(codigo="EAN-1", tnr_id=0, tnr_variation_id=0, stock=0, **extra):
    row = {"Código": codigo, "tnr_id": tnr_id, "tnr_variationID": tnr_variation_id, "stock": stock}
    row.update(extra)
    return row


class TestFaltaVincular:
    def test_unlinked_product_with_existing_tn_variant(self):
        gbp_rows = [_gbp_row(codigo="779123", tnr_id=0)]
        tn_productos = [_tn(sku="779123")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "FALTA_VINCULAR"


class TestFaltaPublicar:
    def test_not_yet_published_and_not_banned(self):
        gbp_rows = [_gbp_row(codigo="000999", tnr_id=0)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "FALTA_PUBLICAR"

    def test_banned_ean_is_excluded_from_actionable_view(self):
        gbp_rows = [_gbp_row(codigo="000999", tnr_id=0)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos, banned_eans={"000999"})

        assert results == []


class TestBanlistScope:
    """Banning an EAN means "we don't want to publish this" — it MUST only
    hide the publish-candidate verdicts (FALTA_PUBLICAR, FALTA_VINCULAR).
    It MUST NOT hide data-quality anomalies (MAL_VINCULADO, MAL_PUBLICADO,
    DUPLICADO): banning is not a way to sweep a broken publication under the
    rug, it only means "don't offer this as something to go publish"."""

    def test_banned_ean_hides_falta_publicar(self):
        gbp_rows = [_gbp_row(codigo="BANNED-1", tnr_id=0)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos, banned_eans={"BANNED-1"})

        assert results == []

    def test_banned_ean_hides_falta_vincular(self):
        gbp_rows = [_gbp_row(codigo="BANNED-2", tnr_id=0)]
        tn_productos = [_tn(sku="BANNED-2")]

        results = compute_verdicts(gbp_rows, tn_productos, banned_eans={"BANNED-2"})

        assert results == []

    def test_banned_ean_does_not_hide_mal_vinculado(self):
        gbp_rows = [_gbp_row(codigo="BANNED-3", tnr_id=501, tnr_variation_id=0)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos, banned_eans={"BANNED-3"})

        assert len(results) == 1
        assert results[0].verdict == "MAL_VINCULADO"

    def test_banned_ean_does_not_hide_mal_publicado(self):
        gbp_rows = [_gbp_row(codigo="BANNED-4", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="999-different")]

        results = compute_verdicts(gbp_rows, tn_productos, banned_eans={"BANNED-4"})

        assert len(results) == 1
        assert results[0].verdict == "MAL_PUBLICADO"

    def test_banned_ean_does_not_hide_duplicado(self):
        gbp_rows = [
            _gbp_row(codigo="BANNED-5", tnr_id=501, tnr_variation_id=12),
            _gbp_row(codigo="BANNED-5-B", tnr_id=501, tnr_variation_id=12),
        ]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="BANNED-5")]

        results = compute_verdicts(gbp_rows, tn_productos, banned_eans={"BANNED-5"})

        assert len(results) == 2
        assert all(r.verdict == "DUPLICADO" for r in results)


class TestMalVinculado:
    def test_linked_product_without_variant(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=0)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "MAL_VINCULADO"

    def test_two_mal_vinculado_rows_sharing_tnr_id_are_not_masked_as_duplicado(self):
        """DUPLICADO grouping keys on (tnr_id, tnr_variationID) but MUST
        require a RESOLVED variant (tnr_variationID > 0). Two rows sharing
        the same tnr_id with unresolved variants (tnr_variationID == 0) both
        group under the same (tnr_id, 0) key if that guard is missing,
        hiding the real MAL_VINCULADO anomaly behind a DUPLICADO label."""
        gbp_rows = [
            _gbp_row(codigo="A", tnr_id=501, tnr_variation_id=0),
            _gbp_row(codigo="B", tnr_id=501, tnr_variation_id=0),
        ]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 2
        assert all(r.verdict == "MAL_VINCULADO" for r in results)


class TestMalPublicado:
    def test_matched_variant_with_mismatched_sku(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="999-different")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "MAL_PUBLICADO"

    def test_resolved_ids_but_no_matching_tn_row_is_mal_publicado(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "MAL_PUBLICADO"

    def test_fully_matched_row_is_ok_not_an_anomaly(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "OK"


class TestDuplicado:
    def test_two_gbp_rows_point_to_same_tn_variant(self):
        gbp_rows = [
            _gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12),
            _gbp_row(codigo="456", tnr_id=501, tnr_variation_id=12),
        ]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 2
        assert all(r.verdict == "DUPLICADO" for r in results)

    def test_multiple_tn_variants_share_one_ean_never_auto_resolved(self):
        gbp_rows = [_gbp_row(codigo="SAME-EAN", tnr_id=0)]
        tn_productos = [
            _tn(product_id=1, variant_id=1, sku="SAME-EAN"),
            _tn(product_id=2, variant_id=1, sku="SAME-EAN"),
        ]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "DUPLICADO"
        # Both conflicting TN rows must be surfaced for human review — never
        # silently narrowed down to a single "correct" one.
        assert len(results[0].tn_matches) == 2

    def test_legitimate_color_split_is_not_treated_as_hard_error(self):
        """A DUPLICADO grouping may be legitimate (single ERP item later split
        into multiple per-color TN publications) — it's still surfaced as
        DUPLICADO for human review, never auto-resolved or auto-deleted."""
        gbp_rows = [
            _gbp_row(codigo="RED", tnr_id=900, tnr_variation_id=1),
            _gbp_row(codigo="BLUE", tnr_id=900, tnr_variation_id=1),
        ]
        tn_productos = [_tn(product_id=900, variant_id=1, sku="RED")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 2
        assert all(r.verdict == "DUPLICADO" for r in results)


class TestVerdictEdgeCases:
    def test_null_variant_sku_never_matches_any_ean(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=0)]
        tn_productos = [_tn(sku=None)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "FALTA_PUBLICAR"

    def test_empty_string_variant_sku_never_matches_any_ean(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=0)]
        tn_productos = [_tn(sku="   ")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "FALTA_PUBLICAR"

    def test_ean_absent_everywhere_follows_falta_publicar_rules(self):
        gbp_rows = [_gbp_row(codigo="NOWHERE", tnr_id=0)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "FALTA_PUBLICAR"


class TestDespublicar:
    """DESPUBLICAR MUST key off TN's real `published` field, never `activo`.

    `activo` only means "present in the last full sync" — the sync sets it
    true for every product the /products endpoint returns, INCLUDING
    unpublished/draft ones. Using it as a "visible in storefront" proxy
    over-flags DESPUBLICAR for products that were never actually published.
    """

    def test_published_true_with_no_stock_is_flagged(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12, stock=0)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", activo=True, published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "OK"
        assert results[0].despublicar is True

    def test_published_true_with_stock_is_not_flagged(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12, stock=5)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", activo=True, published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].despublicar is False

    def test_published_false_with_no_stock_is_never_flagged(self):
        """A draft/unpublished TN product with no stock is not "visible with
        no stock" — it's simply not visible. Must not be DESPUBLICAR."""
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12, stock=0)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", activo=True, published=False)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].despublicar is False

    def test_published_none_with_no_stock_is_fail_safe_not_flagged(self):
        """Rows not yet re-synced (published IS NULL) are UNKNOWN, not
        published — the fail-safe default must never over-claim DESPUBLICAR
        on unknown data. Also a regression guard for the fixed bug:
        `activo=True` with `published` left at its default (None/unset) must
        NOT be treated as published."""
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12, stock=0)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", activo=True, published=None)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].despublicar is False
