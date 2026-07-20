"""
Integration tests for `listar_productos` (GET /productos) promo-type filter
(feature productos-list-promo-filter, backend slice / PR1).

Strategy: `listar_productos` is too complex for a full HTTP TestClient run
against the sqlite test DB — it unconditionally issues raw Postgres-only SQL
(`... WHERE item_id = ANY(:item_ids) ...` against `tienda_nube_productos`)
once the result page is non-empty, which sqlite cannot execute (mirrors the
documented limitation in test_productos_listing_envio.py). We therefore call
`listar_productos(...)` directly (like test_productos_mercadolibre_lite.py
does for a different endpoint) against the real sqlite-backed `db` fixture,
and monkeypatch `db.execute` to short-circuit only the `tienda_nube_productos`
raw query (returning no rows) while every other query (including the ones
this feature adds) runs for real against the test DB.

`fetch_mlas_with_active_promo_type` (mlwebhook DB) is always mocked at the
endpoint import site — the mlwebhook DB is not reachable in tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.api.endpoints.productos_listing import listar_productos


_POSTGRES_ONLY_RAW_SQL_MARKERS = ("tienda_nube_productos", "v_ml_catalog_status_latest")


def _patch_tienda_nube(db):
    """Short-circuit raw Postgres-only ANY() queries (tienda_nube_productos,
    v_ml_catalog_status_latest — unsupported by sqlite) to return no rows,
    leaving every other query (including the ones this feature adds) real.
    """
    original_execute = db.execute

    def _execute_patch(statement, *args, **kwargs):
        if any(marker in str(statement) for marker in _POSTGRES_ONLY_RAW_SQL_MARKERS):
            mock_result = MagicMock()
            mock_result.fetchall.return_value = []
            return mock_result
        return original_execute(statement, *args, **kwargs)

    db.execute = _execute_patch


def _make_producto(item_id: int, marca: str = "Epson") -> ProductoERP:
    return ProductoERP(
        item_id=item_id,
        codigo=f"COD{item_id}",
        descripcion=f"Producto {item_id}",
        marca=marca,
        activo=True,
        costo=100.0,
    )


def _current_user() -> SimpleNamespace:
    return SimpleNamespace(id=1)


class TestPromoTiposAbsentIsNoOp:
    def test_helper_not_called_and_results_unchanged(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.commit()
        _patch_tienda_nube(db)

        with patch("app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type") as mock_helper:
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        mock_helper.assert_not_called()
        assert result.total == 2

    def test_whitespace_or_comma_only_promo_tipos_is_noop(self, db) -> None:
        """A supplied-but-empty promo_tipos (e.g. "  ,  ") parses to zero
        types -> same no-op as an absent param (spec: empty promo_tipos skips
        the filter). Pinned so this stays intentional: helper never called,
        the full catalog is returned (this is NOT a leak — the listing is
        already accessible unfiltered; the filter only narrows)."""
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.commit()
        _patch_tienda_nube(db)

        with patch("app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type") as mock_helper:
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, promo_tipos="  ,  ")

        mock_helper.assert_not_called()
        assert result.total == 2


class TestEmptySetGuard:
    """Empty-set guard: promo_tipos present but the helper finds no matching
    MLAs -> zero products, NOT the unfiltered catalog (dominant correctness
    risk per design Decision 1)."""

    def test_empty_helper_result_yields_empty_page_not_full_catalog(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            return_value=set(),
        ) as mock_helper:
            result = listar_productos(
                db=db, current_user=_current_user(), page=1, page_size=50, promo_tipos="NONEXISTENT_TYPE"
            )

        mock_helper.assert_called_once()
        assert result.total == 0
        assert result.productos == []


class TestFoldBeforeCount:
    """`total` must reflect the filtered set, not the unfiltered catalog."""

    def test_total_reflects_filtered_set(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(_make_producto(3))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            return_value={"MLA1"},
        ):
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, promo_tipos="SMART")

        assert result.total == 1
        assert [p.item_id for p in result.productos] == [1]


class TestMultiTypeOr:
    def test_product_matching_either_type_included(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.add(PublicacionML(mla="MLA2", item_id=2, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            return_value={"MLA1", "MLA2"},
        ) as mock_helper:
            result = listar_productos(
                db=db,
                current_user=_current_user(),
                page=1,
                page_size=50,
                promo_tipos="SMART,SELLER_CAMPAIGN",
            )

        assert result.total == 2
        assert mock_helper.call_args[0][0] == ["SMART", "SELLER_CAMPAIGN"]


class TestModeSwitch:
    def test_default_disponible_passes_applied_only_false(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            return_value={"MLA1"},
        ) as mock_helper:
            listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, promo_tipos="SMART")

        assert mock_helper.call_args[0][1] is False

    def test_aplicada_passes_applied_only_true(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            return_value={"MLA1"},
        ) as mock_helper:
            listar_productos(
                db=db,
                current_user=_current_user(),
                page=1,
                page_size=50,
                promo_tipos="SMART",
                promo_estado="aplicada",
            )

        assert mock_helper.call_args[0][1] is True


class TestCombinationWithExistingFilter:
    def test_ands_with_marcas_filter(self, db) -> None:
        db.add(_make_producto(1, marca="Epson"))
        db.add(_make_producto(2, marca="Canon"))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.add(PublicacionML(mla="MLA2", item_id=2, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            return_value={"MLA1", "MLA2"},
        ):
            result = listar_productos(
                db=db,
                current_user=_current_user(),
                page=1,
                page_size=50,
                promo_tipos="SMART",
                marcas="Epson",
            )

        assert result.total == 1
        assert result.productos[0].item_id == 1


class TestPromoEstadoValidation:
    def test_invalid_promo_estado_raises_422(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with pytest.raises(HTTPException) as exc_info:
            listar_productos(
                db=db,
                current_user=_current_user(),
                page=1,
                page_size=50,
                promo_tipos="SMART",
                promo_estado="bogus",
            )

        assert exc_info.value.status_code == 422


class TestWebhookFailure:
    def test_helper_failure_raises_503(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, promo_tipos="SMART")

        assert exc_info.value.status_code == 503

    def test_unrelated_request_without_promo_tipos_unaffected_by_webhook_down(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
        ) as mock_helper:
            listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        mock_helper.assert_not_called()


# ---------------------------------------------------------------------------
# feature productos-search-mla-promo-operators (PR1, backend slice)
# ---------------------------------------------------------------------------


class TestMlaOperatorLocalFold:
    """`mla:VALUE` and bare-MLA autodetect — local join via PublicacionML,
    NO cross-DB call, never 503s on webhook outage."""

    def test_explicit_mla_operator_matches_owning_product(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(PublicacionML(mla="MLA123", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="mla:MLA123")

        assert result.total == 1
        assert [p.item_id for p in result.productos] == [1]

    def test_unknown_mla_returns_empty_not_full_catalog(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA123", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="mla:MLA999999")

        assert result.total == 0
        assert result.productos == []

    def test_bare_mla_autodetects(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA123456", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="MLA123456")

        assert result.total == 1
        assert [p.item_id for p in result.productos] == [1]

    def test_bare_mla_lowercase_autodetects_case_insensitively(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA123456", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="mla123456")

        assert result.total == 1
        assert [p.item_id for p in result.productos] == [1]

    def test_partial_looking_mla_text_does_not_autodetect(self, db) -> None:
        db.add(_make_producto(1, marca="MLAX"))
        db.commit()
        _patch_tienda_nube(db)

        # "MLAX" does not match ^MLA\d+$ -> falls through to normal text
        # search, matches marca="MLAX".
        result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="MLAX")

        assert result.total == 1

    def test_mla_alone_does_not_autodetect(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        # "mla" alone does not match ^MLA\d+$ and has no colon -> falls
        # through to normal text search (no match against any product).
        result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="mla")

        assert result.total == 0

    def test_mla_operator_does_not_call_cross_db_helper(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA123", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch("app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type") as mock_helper:
            listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="mla:MLA123")

        mock_helper.assert_not_called()

    def test_empty_value_mla_operator_fails_closed(self, db) -> None:
        """B1: `search="mla:"` (explicit operator, empty value) must yield
        ZERO results, never the full catalog."""
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.commit()
        _patch_tienda_nube(db)

        result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="mla:")

        assert result.total == 0
        assert result.productos == []

    def test_mla_operator_unaffected_by_webhook_outage(self, db) -> None:
        """mla: is local-only — must NOT 503 even if the cross-DB helper
        would fail, since it's never called for a pure mla: search."""
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA123", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
        ):
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="mla:MLA123")

        assert result.total == 1


class TestPromoOperatorResolve:
    """`promo:VALUE` — type branch (KNOWN_PROMOTION_TYPES) vs name branch
    (fetch_mlas_by_promo_name), fold-before-count, empty-set guard, 503 on
    failure."""

    def test_known_type_calls_active_promo_type_helper(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with (
            patch(
                "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
                return_value={"MLA1"},
            ) as mock_type_helper,
            patch("app.api.endpoints.productos_listing.fetch_mlas_by_promo_name") as mock_name_helper,
        ):
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="promo:DEAL")

        mock_type_helper.assert_called_once_with(["DEAL"], applied_only=False)
        mock_name_helper.assert_not_called()
        assert result.total == 1

    def test_pure_promo_search_does_not_warn_no_filter(self, db, caplog) -> None:
        """A pure `promo:` search sets no `search_filter` (it resolves via its
        own block), so it must NOT emit the "search_filter quedó en None"
        warning — that log is reserved for a genuine no-op search and firing it
        spuriously desensitizes monitoring."""
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            return_value={"MLA1"},
        ):
            with caplog.at_level("WARNING"):
                listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="promo:DEAL")

        assert not any("search_filter quedó en None" in r.message for r in caplog.records)

    def test_known_type_case_insensitive(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            return_value={"MLA1"},
        ) as mock_type_helper:
            listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="promo:smart")

        mock_type_helper.assert_called_once_with(["SMART"], applied_only=False)

    def test_unknown_value_calls_name_helper(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with (
            patch("app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type") as mock_type_helper,
            patch(
                "app.api.endpoints.productos_listing.fetch_mlas_by_promo_name",
                return_value={"MLA1"},
            ) as mock_name_helper,
        ):
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="promo:FORZA")

        mock_name_helper.assert_called_once_with("FORZA")
        mock_type_helper.assert_not_called()
        assert result.total == 1

    def test_empty_helper_result_yields_empty_page(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_by_promo_name",
            return_value=set(),
        ):
            result = listar_productos(
                db=db, current_user=_current_user(), page=1, page_size=50, search="promo:ZZZNOTHING"
            )

        assert result.total == 0
        assert result.productos == []

    def test_helper_failure_raises_503(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="promo:DEAL")

        assert exc_info.value.status_code == 503

    def test_empty_value_promo_operator_fails_closed(self, db) -> None:
        """B1: `search="promo:"` (explicit operator, empty value) must yield
        ZERO results, never the full catalog."""
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.commit()
        _patch_tienda_nube(db)

        with (
            patch("app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type") as mock_type_helper,
            patch("app.api.endpoints.productos_listing.fetch_mlas_by_promo_name") as mock_name_helper,
        ):
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, search="promo:")

        assert result.total == 0
        assert result.productos == []
        mock_type_helper.assert_not_called()
        mock_name_helper.assert_not_called()

    def test_ands_with_existing_promo_tipos_filter(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.add(PublicacionML(mla="MLA2", item_id=2, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            side_effect=lambda types, applied_only=False: (
                {"MLA1", "MLA2"} if types == ["SELLER_CAMPAIGN"] else {"MLA1"}
            ),
        ):
            result = listar_productos(
                db=db,
                current_user=_current_user(),
                page=1,
                page_size=50,
                promo_tipos="SELLER_CAMPAIGN",
                search="promo:DEAL",
            )

        assert result.total == 1
        assert result.productos[0].item_id == 1

    def test_ands_with_brand_filter(self, db) -> None:
        db.add(_make_producto(1, marca="Epson"))
        db.add(_make_producto(2, marca="Canon"))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.add(PublicacionML(mla="MLA2", item_id=2, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            return_value={"MLA1", "MLA2"},
        ):
            result = listar_productos(
                db=db,
                current_user=_current_user(),
                page=1,
                page_size=50,
                marcas="Epson",
                search="promo:DEAL",
            )

        assert result.total == 1
        assert result.productos[0].item_id == 1


class TestConPromoAplicada:
    """`con_promo_aplicada=true` — products with at least one started promo."""

    def test_only_started_promo_products_included(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.add(PublicacionML(mla="MLA2", item_id=2, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_started",
            return_value={"MLA1"},
        ):
            result = listar_productos(
                db=db, current_user=_current_user(), page=1, page_size=50, con_promo_aplicada=True
            )

        assert result.total == 1
        assert result.productos[0].item_id == 1

    def test_empty_helper_result_yields_empty_page(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_started",
            return_value=set(),
        ):
            result = listar_productos(
                db=db, current_user=_current_user(), page=1, page_size=50, con_promo_aplicada=True
            )

        assert result.total == 0

    def test_helper_failure_raises_503(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_started",
            side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, con_promo_aplicada=True)

        assert exc_info.value.status_code == 503

    def test_absent_param_does_not_call_helper(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch("app.api.endpoints.productos_listing.fetch_mlas_with_started") as mock_helper:
            listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        mock_helper.assert_not_called()


class TestConPromoSinAplicar:
    """`con_promo_sin_aplicar=true` — products with >=1 candidate promo AND
    zero started promos (compound exclusion: a product with both is
    excluded)."""

    def test_candidate_only_product_included(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_candidate_only",
            return_value={"MLA1"},
        ):
            result = listar_productos(
                db=db, current_user=_current_user(), page=1, page_size=50, con_promo_sin_aplicar=True
            )

        assert result.total == 1
        assert result.productos[0].item_id == 1

    def test_product_with_started_excluded_even_with_candidate(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        # The helper itself excludes MLA1 (has a started promo, per its own
        # compound HAVING semantics tested at the unit level) -> empty set
        # here means the endpoint must NOT include item 1.
        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_candidate_only",
            return_value=set(),
        ):
            result = listar_productos(
                db=db, current_user=_current_user(), page=1, page_size=50, con_promo_sin_aplicar=True
            )

        assert result.total == 0

    def test_helper_failure_raises_503(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_candidate_only",
            side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, con_promo_sin_aplicar=True)

        assert exc_info.value.status_code == 503


class TestConPromoAplicadaAndSinAplicarTogether:
    def test_both_true_yields_empty_result_for_disjoint_sets(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.add(PublicacionML(mla="MLA2", item_id=2, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        # Real data is disjoint by construction (a started MLA cannot also
        # be "candidate and zero started"): product 1 has only a started
        # promo, product 2 has only a candidate promo -> the AND of the two
        # filters matches neither.
        with (
            patch(
                "app.api.endpoints.productos_listing.fetch_mlas_with_started",
                return_value={"MLA1"},
            ),
            patch(
                "app.api.endpoints.productos_listing.fetch_mlas_with_candidate_only",
                return_value={"MLA2"},
            ),
        ):
            result = listar_productos(
                db=db,
                current_user=_current_user(),
                page=1,
                page_size=50,
                con_promo_aplicada=True,
                con_promo_sin_aplicar=True,
            )

        assert result.total == 0
