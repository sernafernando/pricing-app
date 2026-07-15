"""RED/GREEN — recompute_item core (SDD promo-price-propagation, slice 3).

TDD: all tests written BEFORE the implementation.

Spec coverage (design #937):
  REQ-1 — per column, write MIN active-promo price across the MLAs
          mapping to it (via pricing_columns.campo_for_pricelist)
  REQ-2 — clasica (pricelist_id=4) writes precio_lista_ml
  REQ-3 — last-write-wins: manual.fecha <= promo activation -> promo
          overwrites; manual.fecha > promo activation -> SKIP (frozen)
  REQ-4 — frozen-on-expiry: no active promos left for a column -> no
          write, no revert (origin/value untouched)
  REQ-5 — fail-closed: cross-DB read error -> no writes at all, error
          propagates to the caller
  REQ-6 — kill-switch (PROMOS_WRITE_ENABLED=False) -> no writes
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.producto import ProductoERP, ProductoPricing, TipoMoneda
from app.models.producto_precio_origen import ProductoPrecioOrigen
from app.models.publicacion_ml import PublicacionML
from app.services.promo_price_propagation import recompute_item


def _make_producto(db, item_id: int = 2001) -> ProductoERP:
    producto = ProductoERP(
        item_id=item_id,
        codigo=f"COD{item_id}",
        descripcion="Producto de prueba",
        subcategoria_id=1,
        costo=1000.0,
        moneda_costo=TipoMoneda.ARS,
        iva=21.0,
    )
    db.add(producto)
    db.commit()
    return producto


def _make_publicacion(db, item_id: int, mla: str, pricelist_id: int) -> PublicacionML:
    pub = PublicacionML(mla=mla, item_id=item_id, pricelist_id=pricelist_id)
    db.add(pub)
    db.commit()
    return pub


def _active_promo(promotion_id: str, price: float, status: str = "started") -> dict:
    return {"promotion_id": promotion_id, "status": status, "price": price}


@pytest.fixture(autouse=True)
def _enable_promo_writes():
    original = settings.PROMOS_WRITE_ENABLED
    settings.PROMOS_WRITE_ENABLED = True
    yield
    settings.PROMOS_WRITE_ENABLED = original


class TestRecomputeItemMinOfActive:
    def test_writes_min_active_price_across_multiple_mlas_same_column(self, db):
        _make_producto(db)
        _make_publicacion(db, 2001, "MLA1", 4)
        _make_publicacion(db, 2001, "MLA2", 4)

        def fake_fetch(mla, active_only=True):
            return {
                "MLA1": [_active_promo("PROMO-A", 900.0)],
                "MLA2": [_active_promo("PROMO-B", 800.0)],
            }[mla]

        with patch(
            "app.services.promo_price_propagation.fetch_item_promotions",
            side_effect=fake_fetch,
        ):
            result = recompute_item(db, 2001)
        db.commit()

        pricing = db.query(ProductoPricing).filter_by(item_id=2001).first()
        assert float(pricing.precio_lista_ml) == 800.0
        assert result.written_columns == ["precio_lista_ml"]

        origen = db.query(ProductoPrecioOrigen).filter_by(item_id=2001, column_key="precio_lista_ml").first()
        assert origen.origen == "promo"
        assert origen.promo_id == "PROMO-B"
        assert origen.mla == "MLA2"

    def test_per_column_mapping_via_pricing_columns(self, db):
        _make_producto(db)
        _make_publicacion(db, 2001, "MLA1", 4)  # clasica
        _make_publicacion(db, 2001, "MLA2", 17)  # 3 cuotas

        def fake_fetch(mla, active_only=True):
            return {
                "MLA1": [_active_promo("PROMO-A", 900.0)],
                "MLA2": [_active_promo("PROMO-C", 500.0)],
            }[mla]

        with patch(
            "app.services.promo_price_propagation.fetch_item_promotions",
            side_effect=fake_fetch,
        ):
            recompute_item(db, 2001)
        db.commit()

        pricing = db.query(ProductoPricing).filter_by(item_id=2001).first()
        assert float(pricing.precio_lista_ml) == 900.0
        assert float(pricing.precio_3_cuotas) == 500.0

    def test_clasica_writes_precio_lista_ml(self, db):
        _make_producto(db)
        _make_publicacion(db, 2001, "MLA1", 4)

        with patch(
            "app.services.promo_price_propagation.fetch_item_promotions",
            return_value=[_active_promo("PROMO-A", 700.0)],
        ):
            result = recompute_item(db, 2001)

        assert result.columns[0].column_key == "precio_lista_ml"


class TestRecomputeItemLastWriteWins:
    def test_manual_older_than_promo_activation_is_overwritten(self, db):
        _make_producto(db)
        _make_publicacion(db, 2001, "MLA1", 4)
        manual_fecha = datetime(2026, 1, 1, tzinfo=UTC)
        db.add(
            ProductoPrecioOrigen(
                item_id=2001, column_key="precio_lista_ml", origen="manual", fecha=manual_fecha
            )
        )
        db.commit()

        activation_time = datetime(2026, 1, 2, tzinfo=UTC)
        with patch(
            "app.services.promo_price_propagation.fetch_item_promotions",
            return_value=[_active_promo("PROMO-A", 700.0)],
        ):
            result = recompute_item(db, 2001, now=activation_time)
        db.commit()

        pricing = db.query(ProductoPricing).filter_by(item_id=2001).first()
        assert float(pricing.precio_lista_ml) == 700.0
        assert result.columns[0].status == "written"
        origen = db.query(ProductoPrecioOrigen).filter_by(item_id=2001, column_key="precio_lista_ml").first()
        assert origen.origen == "promo"

    def test_manual_newer_than_promo_activation_is_skipped(self, db):
        _make_producto(db)
        _make_publicacion(db, 2001, "MLA1", 4)
        manual_fecha = datetime(2026, 1, 5, tzinfo=UTC)
        db.add(
            ProductoPrecioOrigen(
                item_id=2001, column_key="precio_lista_ml", origen="manual", fecha=manual_fecha
            )
        )
        pricing = ProductoPricing(item_id=2001, precio_lista_ml=1234.0)
        db.add(pricing)
        db.commit()

        activation_time = datetime(2026, 1, 2, tzinfo=UTC)
        with patch(
            "app.services.promo_price_propagation.fetch_item_promotions",
            return_value=[_active_promo("PROMO-A", 700.0)],
        ):
            result = recompute_item(db, 2001, now=activation_time)
        db.commit()

        pricing = db.query(ProductoPricing).filter_by(item_id=2001).first()
        assert float(pricing.precio_lista_ml) == 1234.0
        assert result.columns[0].status == "skipped_frozen_manual"
        origen = db.query(ProductoPrecioOrigen).filter_by(item_id=2001, column_key="precio_lista_ml").first()
        assert origen.origen == "manual"


class TestRecomputeItemFrozenOnExpiry:
    def test_no_active_promos_left_no_write_no_revert(self, db):
        _make_producto(db)
        _make_publicacion(db, 2001, "MLA1", 4)
        pricing = ProductoPricing(item_id=2001, precio_lista_ml=999.0)
        db.add(pricing)
        db.add(
            ProductoPrecioOrigen(
                item_id=2001,
                column_key="precio_lista_ml",
                origen="promo",
                promo_id="PROMO-OLD",
                mla="MLA1",
            )
        )
        db.commit()

        with patch(
            "app.services.promo_price_propagation.fetch_item_promotions",
            return_value=[],
        ):
            result = recompute_item(db, 2001)
        db.commit()

        pricing = db.query(ProductoPricing).filter_by(item_id=2001).first()
        assert float(pricing.precio_lista_ml) == 999.0
        assert result.columns[0].status == "skipped_no_active_promo"
        origen = db.query(ProductoPrecioOrigen).filter_by(item_id=2001, column_key="precio_lista_ml").first()
        assert origen.origen == "promo"
        assert origen.promo_id == "PROMO-OLD"


class TestRecomputeItemFailClosed:
    def test_cross_db_error_raises_and_writes_nothing(self, db):
        _make_producto(db)
        _make_publicacion(db, 2001, "MLA1", 4)
        _make_publicacion(db, 2001, "MLA2", 17)

        def fake_fetch(mla, active_only=True):
            if mla == "MLA1":
                return [_active_promo("PROMO-A", 700.0)]
            raise RuntimeError("ML_WEBHOOK_DB_URL not configured")

        with patch(
            "app.services.promo_price_propagation.fetch_item_promotions",
            side_effect=fake_fetch,
        ):
            with pytest.raises(RuntimeError):
                recompute_item(db, 2001)

        pricing = db.query(ProductoPricing).filter_by(item_id=2001).first()
        assert pricing is None
        assert db.query(ProductoPrecioOrigen).filter_by(item_id=2001).count() == 0


class TestRecomputeItemKillSwitch:
    def test_kill_switch_off_no_writes(self, db):
        _make_producto(db)
        _make_publicacion(db, 2001, "MLA1", 4)
        settings.PROMOS_WRITE_ENABLED = False

        with patch(
            "app.services.promo_price_propagation.fetch_item_promotions",
            return_value=[_active_promo("PROMO-A", 700.0)],
        ):
            result = recompute_item(db, 2001)

        pricing = db.query(ProductoPricing).filter_by(item_id=2001).first()
        assert pricing is None
        assert result.columns[0].status == "skipped_disabled"


class TestRecomputeItemNoPublications:
    def test_no_publicaciones_ml_no_columns(self, db):
        _make_producto(db)
        result = recompute_item(db, 2001)
        assert result.columns == []
