"""Unit tests for the TN reconciliation verdict taxonomy (Slice 1, read-only).

These tests cover `compute_verdicts` in isolation: no HTTP, no GBP fetch, no
DB session — only the pure EAN-join + verdict logic. GBP fetch failure
handling (`fetch_gbp_report_78`) is covered separately.
"""

from app.models.tienda_nube_producto import TiendaNubeProducto
from app.services.tn_reconciliation_service import compute_verdicts, normalize_gtin


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


class TestNormalizeGtin:
    """Task 1: exhaustive normalization matrix (proposal + spec §SKU/EAN
    Matching Normalization)."""

    def test_leading_zero_gbp_only(self):
        assert normalize_gtin("023942321477") == normalize_gtin("23942321477")

    def test_extra_leading_zero_tn_only(self):
        assert normalize_gtin("023942321552") == normalize_gtin("0023942321552")

    def test_00_prefix(self):
        assert normalize_gtin("00123") == normalize_gtin("123")

    def test_equal_after_normalization_variants(self):
        assert normalize_gtin("000123") == normalize_gtin("00123") == normalize_gtin("123")

    def test_exact_raw_match(self):
        assert normalize_gtin("23942321477") == normalize_gtin("23942321477")

    def test_genuinely_different_gtins_no_collision(self):
        assert normalize_gtin("023942321477") != normalize_gtin("023942321478")

    def test_whitespace_padded(self):
        assert normalize_gtin("  23942321477  ") == normalize_gtin("23942321477")

    def test_empty_string_never_equals_empty_string(self):
        assert normalize_gtin("") != normalize_gtin("")

    def test_none_never_equals_none(self):
        assert normalize_gtin(None) != normalize_gtin(None)

    def test_all_zero_never_equals_all_zero(self):
        assert normalize_gtin("0000") != normalize_gtin("0000")

    def test_non_numeric_never_equals_non_numeric(self):
        assert normalize_gtin("ABC123") != normalize_gtin("ABC123")

    def test_sentinel_never_equals_empty_ean(self):
        assert normalize_gtin(None) != normalize_gtin("")
        assert normalize_gtin("ABC123") != normalize_gtin("0000")


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

    def test_dead_claimed_link_but_ean_resolves_real_published_product_is_ok(self):
        """Bug fix: a stale/dead tnr_id/tnr_variationID link (doesn't resolve
        to any TN row) must NOT by itself force MAL_PUBLICADO when the row's
        EAN independently resolves a real, correctly-SKU'd, published TN
        product. The product IS correctly published — only the ERP's cached
        pointer is wrong, which is not a data-quality anomaly to surface."""
        gbp_rows = [_gbp_row(codigo="843367123476", tnr_id=999, tnr_variation_id=88)]
        tn_productos = [_tn(product_id=42, variant_id=7, sku="843367123476", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "OK"
        assert results[0].tn_presence == "published"
        assert len(results[0].tn_matches) == 1
        assert results[0].tn_matches[0].product_id == 42
        assert results[0].tn_matches[0].variant_id == 7

    def test_dead_claimed_link_ean_resolves_only_via_gtin_normalization_is_por_corregir(self):
        gbp_rows = [_gbp_row(codigo="023942321477", tnr_id=999, tnr_variation_id=88)]
        tn_productos = [_tn(product_id=42, variant_id=7, sku="23942321477", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "POR_CORREGIR"
        assert results[0].tn_presence == "published"

    def test_dead_claimed_link_no_ean_match_at_all_stays_mal_publicado(self):
        gbp_rows = [_gbp_row(codigo="000000000000", tnr_id=999, tnr_variation_id=88)]
        tn_productos = [_tn(product_id=42, variant_id=7, sku="999999999999", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "MAL_PUBLICADO"
        assert results[0].tn_presence == "not_in_tn"


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

    def test_despublicar_is_not_dropped_on_duplicado_rows(self):
        """`despublicar` is computed above the branch dispatch and every
        other branch propagates it — the two DUPLICADO-returning branches
        must too. In the "Todos" sub-tab (which shows the Despublicar column
        AND includes DUPLICADO rows), a published/visible/zero-stock EAN
        must still show despublicar=True even though it's also duplicated —
        that's the case where the flag matters most."""
        gbp_rows = [
            _gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12, stock=0),
            _gbp_row(codigo="456", tnr_id=501, tnr_variation_id=12, stock=0),
        ]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 2
        assert all(r.verdict == "DUPLICADO" for r in results)
        assert any(r.despublicar is True for r in results)

    def test_despublicar_not_dropped_on_multiple_tn_variants_duplicado(self):
        """Same bug, other DUPLICADO branch (multiple TN variants share one
        EAN, tnr_id == 0)."""
        gbp_rows = [_gbp_row(codigo="SAME-EAN", tnr_id=0, stock=0)]
        tn_productos = [
            _tn(product_id=1, variant_id=1, sku="SAME-EAN", published=True),
            _tn(product_id=2, variant_id=1, sku="SAME-EAN", published=True),
        ]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "DUPLICADO"
        assert results[0].despublicar is True


class TestLeadingZeroMatching:
    """Task 1/3: leading-zero-only differences must link (FALTA_VINCULAR),
    never false MAL_PUBLICADO/FALTA_PUBLICAR — regression target for the
    proposal's root-cause bug."""

    def test_leading_zero_on_gbp_side_only_links(self):
        gbp_rows = [_gbp_row(codigo="023942321477", tnr_id=0)]
        tn_productos = [_tn(sku="23942321477")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "FALTA_VINCULAR"

    def test_extra_leading_zero_on_tn_side_links(self):
        gbp_rows = [_gbp_row(codigo="023942321552", tnr_id=0)]
        tn_productos = [_tn(sku="0023942321552")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "FALTA_VINCULAR"

    def test_different_gtins_do_not_collide(self):
        gbp_rows = [_gbp_row(codigo="023942321477", tnr_id=0)]
        tn_productos = [_tn(sku="023942321478")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "FALTA_PUBLICAR"


class TestGtinCollisionDuplicado:
    """GTIN-normalization edge case (reliability review follow-up): when an
    UNLINKED GBP row's EAN normalizes to a GTIN shared by TWO DISTINCT TN
    products, that's a genuine "one EAN -> multiple TN variants" duplicate
    (Verdict Edge Cases: never silently resolved to one arbitrary variant)
    — it MUST classify as DUPLICADO, not FALTA_VINCULAR, even though the
    collision only exists because of leading-zero normalization. This is
    intended behavior, not a regression: two TN products both resolving to
    the same normalized GTIN is exactly the ambiguity DUPLICADO exists to
    surface for human review."""

    def test_gtin_collision_across_two_distinct_tn_products_is_duplicado(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=0)]
        tn_productos = [
            _tn(product_id=1, variant_id=1, sku="123"),
            _tn(product_id=2, variant_id=1, sku="0123"),
        ]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "DUPLICADO"
        matched_product_ids = {tn.product_id for tn in results[0].tn_matches}
        assert matched_product_ids == {1, 2}
        assert results[0].tn_presence != "not_in_tn"

    def test_single_tn_product_leading_zero_still_links_not_duplicado(self):
        """Contrast case: only ONE TN product resolves (no genuine
        collision) — leading-zero-only difference must still link as
        FALTA_VINCULAR, exactly as before this follow-up."""
        gbp_rows = [_gbp_row(codigo="123", tnr_id=0)]
        tn_productos = [_tn(product_id=1, variant_id=1, sku="0123")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "FALTA_VINCULAR"


class TestPorCorregir:
    """Task 3: OK vs POR_CORREGIR vs MAL_PUBLICADO classification order."""

    def test_exact_raw_match_is_ok(self):
        gbp_rows = [_gbp_row(codigo="23942321477", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="23942321477")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "OK"

    def test_raw_differs_normalized_equal_is_por_corregir(self):
        gbp_rows = [_gbp_row(codigo="023942321477", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="23942321477")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "POR_CORREGIR"

    def test_no_match_under_any_normalization_is_mal_publicado(self):
        gbp_rows = [_gbp_row(codigo="023942321477", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="999999999")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "MAL_PUBLICADO"


class TestTnPresence:
    """Task 5: tn_presence computation matrix + DUPLICADO composition."""

    def test_published_true_is_published(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert results[0].tn_presence == "published"

    def test_published_false_is_draft(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", published=False)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert results[0].tn_presence == "draft"

    def test_published_none_is_unknown(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", published=None)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert results[0].tn_presence == "unknown"

    def test_no_resolving_product_is_not_in_tn(self):
        gbp_rows = [_gbp_row(codigo="NOWHERE", tnr_id=0)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos)

        assert results[0].tn_presence == "not_in_tn"

    def test_no_resolving_product_via_tnr_link_is_not_in_tn(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos)

        assert results[0].verdict == "MAL_PUBLICADO"
        assert results[0].tn_presence == "not_in_tn"

    def test_duplicado_with_not_in_tn_presence(self):
        gbp_rows = [_gbp_row(codigo="SAME-EAN", tnr_id=0)]
        tn_productos = []
        # Force DUPLICADO via multiple resolved tnr links sharing one pair,
        # but with the shared TN product NOT existing (never synced).
        gbp_rows = [
            _gbp_row(codigo="A", tnr_id=900, tnr_variation_id=1),
            _gbp_row(codigo="B", tnr_id=900, tnr_variation_id=1),
        ]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 2
        assert all(r.verdict == "DUPLICADO" for r in results)
        assert all(r.tn_presence == "not_in_tn" for r in results)

    def test_duplicado_with_published_presence(self):
        gbp_rows = [
            _gbp_row(codigo="RED", tnr_id=900, tnr_variation_id=1),
            _gbp_row(codigo="BLUE", tnr_id=900, tnr_variation_id=1),
        ]
        tn_productos = [_tn(product_id=900, variant_id=1, sku="RED", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 2
        assert all(r.verdict == "DUPLICADO" for r in results)
        assert all(r.tn_presence == "published" for r in results)


class TestFaltaVincularExposesIds:
    """Task 7: FALTA_VINCULAR rows expose the matched TN product_id/variant_id."""

    def test_resolving_falta_vincular_carries_matched_ids(self):
        gbp_rows = [_gbp_row(codigo="779123", tnr_id=0)]
        tn_productos = [_tn(product_id=42, variant_id=7, sku="779123")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "FALTA_VINCULAR"
        assert results[0].product_id == 42
        assert results[0].variant_id == 7

    def test_falta_publicar_has_null_ids(self):
        gbp_rows = [_gbp_row(codigo="000999", tnr_id=0)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "FALTA_PUBLICAR"
        assert results[0].product_id is None
        assert results[0].variant_id is None


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


class TestReasonRegressionUnaffectedVerdicts:
    """PR1 regression guard (RED first): every existing verdict/stock/
    despublicar/tn_presence assertion in this file MUST keep passing after
    the reason/reason_detail fields are added — they are purely additive.
    This class pins that `reason`/`reason_detail` are `None` for verdicts
    outside the MAL_PUBLICADO/MAL_VINCULADO scope."""

    def test_falta_publicar_has_no_reason(self):
        gbp_rows = [_gbp_row(codigo="000999", tnr_id=0)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos)

        assert results[0].verdict == "FALTA_PUBLICAR"
        assert results[0].reason is None
        assert results[0].reason_detail is None

    def test_falta_vincular_has_no_reason(self):
        gbp_rows = [_gbp_row(codigo="779123", tnr_id=0)]
        tn_productos = [_tn(sku="779123")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert results[0].verdict == "FALTA_VINCULAR"
        assert results[0].reason is None

    def test_ok_has_no_reason(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert results[0].verdict == "OK"
        assert results[0].reason is None

    def test_por_corregir_has_no_reason(self):
        gbp_rows = [_gbp_row(codigo="023942321477", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="23942321477")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert results[0].verdict == "POR_CORREGIR"
        assert results[0].reason is None

    def test_duplicado_has_no_reason(self):
        gbp_rows = [
            _gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12),
            _gbp_row(codigo="456", tnr_id=501, tnr_variation_id=12),
        ]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert all(r.reason is None for r in results)


class TestReasonTaxonomy:
    """PR1 additive scope: DEAD_LINK / SKU_MISMATCH / NO_VARIANT_LINK reason
    codes plus their concrete operands, layered on top of MAL_PUBLICADO and
    MAL_VINCULADO without changing either verdict's value."""

    def test_dead_link_no_ean_match_at_all(self):
        gbp_rows = [_gbp_row(codigo="000000000000", tnr_id=999, tnr_variation_id=88)]
        tn_productos = [_tn(product_id=42, variant_id=7, sku="999999999999", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "MAL_PUBLICADO"
        assert results[0].reason == "DEAD_LINK"
        assert results[0].reason_detail["claimed_tnr_id"] == 999
        assert results[0].reason_detail["claimed_tnr_variation_id"] == 88
        assert results[0].reason_detail["expected_ean"] == "000000000000"
        assert results[0].reason_detail["tn_sku_found"] is None

    def test_sku_mismatch_claimed_tn_exists_but_sku_differs(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="999-different")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "MAL_PUBLICADO"
        assert results[0].reason == "SKU_MISMATCH"
        assert results[0].reason_detail["tn_sku_found"] == "999-different"
        assert results[0].reason_detail["expected_ean"] == "123"
        assert results[0].reason_detail["claimed_tnr_id"] == 501
        assert results[0].reason_detail["claimed_tnr_variation_id"] == 12

    def test_leading_zero_only_difference_is_not_sku_mismatch(self):
        """POR_CORREGIR (leading-zero-only) must never get a MAL_PUBLICADO-
        scoped reason code — reason stays None outside its scope."""
        gbp_rows = [_gbp_row(codigo="023942321477", tnr_id=501, tnr_variation_id=12)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="23942321477")]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert results[0].verdict == "POR_CORREGIR"
        assert results[0].reason is None

    def test_no_variant_link_tnr_id_without_variation_id(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=0)]
        tn_productos = []

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].verdict == "MAL_VINCULADO"
        assert results[0].reason == "NO_VARIANT_LINK"
        assert results[0].reason_detail["claimed_tnr_id"] == 501
        assert results[0].reason_detail["claimed_tnr_variation_id"] is None
        assert results[0].reason_detail["expected_ean"] == "123"
        assert results[0].reason_detail["tn_sku_found"] is None


class TestDespublicarUnknownStock:
    """Round 7, item 2: unknown `stock` must be treated the same way unknown
    `published` already is — as UNKNOWN, never coerced to a specific value
    that happens to also be the value that triggers the flag. `_as_int`
    collapsing a missing/empty/unparseable stock to `0` (its generic
    numeric default) directly contradicts that, since `0` is exactly the
    value DESPUBLICAR keys on — every published EAN on a row with no/bad
    `stock` data would otherwise get silently flagged."""

    def test_stock_key_entirely_absent_is_not_flagged(self):
        gbp_rows = [{"Código": "123", "tnr_id": 501, "tnr_variationID": 12}]  # no "stock" key at all
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].despublicar is False

    def test_stock_empty_string_is_not_flagged(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12, stock="")]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].despublicar is False

    def test_stock_non_numeric_is_not_flagged(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12, stock="N/D")]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].despublicar is False

    def test_stock_none_is_not_flagged(self):
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12, stock=None)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].despublicar is False

    def test_stock_genuinely_zero_with_visible_row_is_still_flagged(self):
        """Regression guard: fixing the unknown-stock fail-safe must not
        also suppress the genuine, correctly-parsed zero-stock case."""
        gbp_rows = [_gbp_row(codigo="123", tnr_id=501, tnr_variation_id=12, stock=0)]
        tn_productos = [_tn(product_id=501, variant_id=12, sku="123", published=True)]

        results = compute_verdicts(gbp_rows, tn_productos)

        assert len(results) == 1
        assert results[0].despublicar is True
