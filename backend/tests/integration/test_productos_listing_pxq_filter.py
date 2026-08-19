"""Integration tests for `listar_productos` (GET /productos) wholesale-tier
(PxQ) filter and quick view.

Same strategy — and same reasons — as
`test_productos_listing_promo_filter.py`: `listar_productos` is called
directly against the sqlite-backed `db` fixture with the Postgres-only raw
queries short-circuited, and the cross-DB (mlwebhook) readers are mocked at
the endpoint import site.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.services.ml_pxq_tiers_read_service import PxqTier
from app.api.endpoints.productos_listing import listar_productos


_POSTGRES_ONLY_RAW_SQL_MARKERS = ("tienda_nube_productos", "v_ml_catalog_status_latest")

_FILTER_READER = "app.api.endpoints.productos_listing.fetch_mlas_with_pxq_tiers"
_QUICKVIEW_READER = "app.api.endpoints.productos_listing.fetch_pxq_tiers_by_mla"


def _patch_tienda_nube(db):
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


class TestConPxqAbsentIsNoOp:
    def test_reader_not_called_and_results_unchanged(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.commit()
        _patch_tienda_nube(db)

        with patch(_FILTER_READER) as mock_reader:
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        mock_reader.assert_not_called()
        assert result.total == 2

    def test_con_pxq_false_is_also_a_noop(self, db) -> None:
        """`con_pxq` is a presence toggle like the other listing chips: only
        True narrows. False is treated as "chip off", never as "show me the
        products WITHOUT tiers" — pinned so the semantics stay deliberate."""
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(_FILTER_READER) as mock_reader:
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, con_pxq=False)

        mock_reader.assert_not_called()
        assert result.total == 1


class TestPxqFilterFold:
    def test_only_products_with_tiers_included(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.add(PublicacionML(mla="MLA2", item_id=2, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(_FILTER_READER, return_value={"MLA1"}), patch(_QUICKVIEW_READER, return_value={}):
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, con_pxq=True)

        assert result.total == 1
        assert [p.item_id for p in result.productos] == [1]


class TestEmptySetGuard:
    """Empty reader result -> zero products, NOT the unfiltered catalog."""

    def test_empty_reader_result_yields_empty_page_not_full_catalog(self, db) -> None:
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.commit()
        _patch_tienda_nube(db)

        with patch(_FILTER_READER, return_value=set()) as mock_reader:
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, con_pxq=True)

        mock_reader.assert_called_once()
        assert result.total == 0
        assert result.productos == []


class TestCombinationWithExistingFilters:
    def test_ands_with_marcas_filter(self, db) -> None:
        db.add(_make_producto(1, marca="Epson"))
        db.add(_make_producto(2, marca="Canon"))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.add(PublicacionML(mla="MLA2", item_id=2, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(_FILTER_READER, return_value={"MLA1", "MLA2"}), patch(_QUICKVIEW_READER, return_value={}):
            result = listar_productos(
                db=db, current_user=_current_user(), page=1, page_size=50, con_pxq=True, marcas="Epson"
            )

        assert result.total == 1
        assert result.productos[0].item_id == 1

    def test_intersects_with_promo_filter_not_replaces_it(self, db) -> None:
        """Both filters active -> INTERSECTION (product 1 only), never the
        union and never one filter silently winning over the other."""
        db.add(_make_producto(1))
        db.add(_make_producto(2))
        db.add(_make_producto(3))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.add(PublicacionML(mla="MLA2", item_id=2, activo=True))
        db.add(PublicacionML(mla="MLA3", item_id=3, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with (
            patch(_FILTER_READER, return_value={"MLA1", "MLA2"}),
            patch(
                "app.api.endpoints.productos_listing.fetch_mlas_with_active_promo_type",
                return_value={"MLA1", "MLA3"},
            ),
            patch(_QUICKVIEW_READER, return_value={}),
        ):
            result = listar_productos(
                db=db, current_user=_current_user(), page=1, page_size=50, con_pxq=True, promo_tipos="SMART"
            )

        assert [p.item_id for p in result.productos] == [1]


class TestWebhookFailure:
    def test_reader_failure_raises_503(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(_FILTER_READER, side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada")):
            with pytest.raises(HTTPException) as exc_info:
                listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, con_pxq=True)

        assert exc_info.value.status_code == 503

    def test_503_detail_names_the_filter_the_user_actually_turned_on(self, db) -> None:
        """The user ticked "precios mayoristas"; being told that *promociones*
        are unavailable sends them looking at the wrong feature."""
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(_FILTER_READER, side_effect=RuntimeError("down")):
            with pytest.raises(HTTPException) as exc_info:
                listar_productos(db=db, current_user=_current_user(), page=1, page_size=50, con_pxq=True)

        assert "mayorista" in exc_info.value.detail.lower()
        assert "promocion" not in exc_info.value.detail.lower()

    def test_unrelated_request_unaffected_by_webhook_down(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(_FILTER_READER, side_effect=RuntimeError("down")) as mock_reader:
            listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        mock_reader.assert_not_called()


class TestQuickView:
    def test_tier_count_and_cheapest_amount_exposed(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        tiers = {
            "MLA1": [
                PxqTier(quantity=2, amount=50000.0),
                PxqTier(quantity=5, amount=42000.0),
                PxqTier(quantity=10, amount=37800.0),
            ]
        }
        with patch(_QUICKVIEW_READER, return_value=tiers) as mock_reader:
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        mock_reader.assert_called_once()
        assert mock_reader.call_args[0][0] == ["MLA1"]
        producto = result.productos[0]
        assert producto.pxq_tramos == 3
        assert producto.pxq_precio_desde == 37800.0

    def test_product_without_tiers_reports_nothing(self, db) -> None:
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(_QUICKVIEW_READER, return_value={}):
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        assert result.productos[0].pxq_tramos is None
        assert result.productos[0].pxq_precio_desde is None

    def test_multiple_mlas_report_deepest_ladder_and_global_cheapest(self, db) -> None:
        """Two publications of the same product: the chip shows the DEEPEST
        single ladder (never the sum, which would double-count a shared
        ladder) and the cheapest amount across all of them."""
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.add(PublicacionML(mla="MLA2", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        tiers = {
            "MLA1": [PxqTier(quantity=2, amount=50000.0), PxqTier(quantity=5, amount=42000.0)],
            "MLA2": [PxqTier(quantity=3, amount=39000.0)],
        }
        with patch(_QUICKVIEW_READER, return_value=tiers):
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        assert result.productos[0].pxq_tramos == 2
        assert result.productos[0].pxq_precio_desde == 39000.0

    def test_quickview_failure_is_fail_open_not_503(self, db) -> None:
        """The quick view is decoration: a mlwebhook outage must degrade it to
        "no chip", never take the whole listing down. (The 503 fail-closed
        path belongs to the FILTER, where returning extra rows would lie.)"""
        db.add(_make_producto(1))
        db.add(PublicacionML(mla="MLA1", item_id=1, activo=True))
        db.commit()
        _patch_tienda_nube(db)

        with patch(_QUICKVIEW_READER, side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada")):
            result = listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        assert result.total == 1
        assert result.productos[0].pxq_tramos is None

    def test_no_mlas_on_page_issues_no_cross_db_call(self, db) -> None:
        db.add(_make_producto(1))
        db.commit()
        _patch_tienda_nube(db)

        with patch(_QUICKVIEW_READER) as mock_reader:
            listar_productos(db=db, current_user=_current_user(), page=1, page_size=50)

        mock_reader.assert_not_called()
