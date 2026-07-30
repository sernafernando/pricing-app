"""
Integration tests for `listar_productos` (GET /productos) official-store filter
(feature promos-catalog-prices-and-official-store, slice A).

Regression scenario: before this fix, `productos_listing.py:699-710` was an
unreachable `if False:` block — the endpoint declared a `tienda_oficial`
param but silently ignored it, returning the unfiltered catalog. These tests
prove the filter now actually narrows the result set.

Strategy mirrors `test_productos_listing_promo_filter.py`: call
`listar_productos(...)` directly against the real sqlite-backed `db` fixture,
patching only the Postgres-only raw SQL markers this endpoint also issues.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.producto import ProductoERP
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.api.endpoints.productos_listing import listar_productos


_POSTGRES_ONLY_RAW_SQL_MARKERS = ("tienda_nube_productos", "v_ml_catalog_status_latest")


def _patch_tienda_nube(db):
    original_execute = db.execute

    def _execute_patch(statement, *args, **kwargs):
        if any(marker in str(statement) for marker in _POSTGRES_ONLY_RAW_SQL_MARKERS):
            mock_result = MagicMock()
            mock_result.fetchall.return_value = []
            return mock_result
        return original_execute(statement, *args, **kwargs)

    db.execute = _execute_patch


def _make_producto(item_id: int) -> ProductoERP:
    return ProductoERP(
        item_id=item_id,
        codigo=f"COD{item_id}",
        descripcion=f"Producto {item_id}",
        marca="Epson",
        activo=True,
        costo=100.0,
    )


def _make_publicacion(item_id: int, mla: str, official_store_id) -> MercadoLibreItemPublicado:
    return MercadoLibreItemPublicado(
        item_id=item_id,
        mlp_publicationID=mla,
        mlp_official_store_id=official_store_id,
    )


def _current_user() -> SimpleNamespace:
    return SimpleNamespace(id=1)


class TestOfficialStoreFilterCsv:
    def test_single_store_id_narrows_result(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(_make_publicacion(1, "MLA1", 57997))
        db.add(_make_publicacion(2, "MLA2", 2645))
        db.commit()
        _patch_tienda_nube(db)

        result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, tienda_oficial="57997")

        assert result.total == 1
        assert [p.item_id for p in result.productos] == [1]

    def test_multi_store_csv_matches_either(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(_make_producto(3))
        db.add(_make_publicacion(1, "MLA1", 57997))
        db.add(_make_publicacion(2, "MLA2", 2645))
        db.add(_make_publicacion(3, "MLA3", 144))
        db.commit()
        _patch_tienda_nube(db)

        result = listar_productos(
            db=db, current_user=_current_user(), page=1, page_size=50, tienda_oficial="57997,2645"
        )

        assert result.total == 2
        assert sorted(p.item_id for p in result.productos) == [1, 2]

    def test_regression_pre_fix_if_false_returned_unfiltered_set(self, db) -> None:
        """The dead `if False:` block used to make this param a no-op — the
        filtered count must be strictly less than the unfiltered count."""
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(_make_publicacion(1, "MLA1", 57997))
        db.add(_make_publicacion(2, "MLA2", 2645))
        db.commit()
        _patch_tienda_nube(db)

        unfiltered = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)
        filtered = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, tienda_oficial="57997")

        assert unfiltered.total == 2
        assert filtered.total < unfiltered.total
        assert filtered.total == 1


class TestOfficialStoreFilterSinTienda:
    def test_sin_tienda_sentinel_matches_no_store(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(_make_publicacion(1, "MLA1", None))
        db.add(_make_publicacion(2, "MLA2", 2645))
        db.commit()
        _patch_tienda_nube(db)

        result = listar_productos(
            db=db, current_user=_current_user(), page=1, page_size=50, tienda_oficial="sin_tienda"
        )

        assert result.total == 1
        assert [p.item_id for p in result.productos] == [1]

    def test_mixed_csv_ids_and_sin_tienda(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(_make_producto(3))
        db.add(_make_publicacion(1, "MLA1", None))
        db.add(_make_publicacion(2, "MLA2", 2645))
        db.add(_make_publicacion(3, "MLA3", 144))
        db.commit()
        _patch_tienda_nube(db)

        result = listar_productos(
            db=db, current_user=_current_user(), page=1, page_size=50, tienda_oficial="2645,sin_tienda"
        )

        assert result.total == 2
        assert sorted(p.item_id for p in result.productos) == [1, 2]


class TestOfficialStoreFilterEdgeCases:
    def test_invalid_token_raises_400(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with pytest.raises(HTTPException) as exc_info:
            listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, tienda_oficial="not_a_number")

        assert exc_info.value.status_code == 400

    def test_absent_param_returns_unfiltered(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(_make_publicacion(1, "MLA1", 57997))
        db.add(_make_publicacion(2, "MLA2", 2645))
        db.commit()
        _patch_tienda_nube(db)

        result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        assert result.total == 2
