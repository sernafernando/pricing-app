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

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type"
        ) as mock_helper:
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

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
            result = listar_productos(
                db=db, current_user=_current_user(), page=1, page_size=50, promo_tipos="SMART"
            )

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
                listar_productos(
                    db=db, current_user=_current_user(), page=1, page_size=50, promo_tipos="SMART"
                )

        assert exc_info.value.status_code == 503

    def test_unrelated_request_without_promo_tipos_unaffected_by_webhook_down(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(
            "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
            side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
        ) as mock_helper:
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        mock_helper.assert_not_called()
        assert result.total == 1
