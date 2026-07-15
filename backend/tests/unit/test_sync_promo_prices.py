"""RED/GREEN — periodic promo-price sync job (SDD promo-price-propagation,
slice 4).

Spec coverage (design #937, MUST-RESOLVE #2):
  REQ-1 — kill-switch off -> exits before any read/write (no engine call)
  REQ-2 — watermark selects only updated_at>watermark, active
          (candidate|started) rows, in ONE query
  REQ-3 — affected MLAs -> item_id mapping via PublicacionML
  REQ-4 — recompute_item called with now=activation_time (max updated_at
          among that item's newly-active rows) — the no-clobber-manual
          guard: a manual edit strictly after activation is not overwritten
  REQ-5 — watermark advances only after a fully successful pass, to the
          max updated_at processed; not advanced past an aborted item
  REQ-6 — idempotent empty run: no newly-active rows -> no writes, watermark
          unchanged
  REQ-7 — a per-item recompute failure is isolated: other items still
          processed
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.models.producto import ProductoERP, ProductoPricing, TipoMoneda
from app.models.producto_precio_origen import ProductoPrecioOrigen
from app.models.promo_sync_watermark import get_watermark
from app.models.publicacion_ml import PublicacionML
from app.scripts import sync_promo_prices


def _make_producto(db, item_id: int) -> ProductoERP:
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


def _make_publicacion(db, item_id: int, mla: str, pricelist_id: int = 4) -> PublicacionML:
    pub = PublicacionML(mla=mla, item_id=item_id, pricelist_id=pricelist_id)
    db.add(pub)
    db.commit()
    return pub


@pytest.fixture(autouse=True)
def _enable_promo_writes():
    original = settings.PROMOS_WRITE_ENABLED
    settings.PROMOS_WRITE_ENABLED = True
    yield
    settings.PROMOS_WRITE_ENABLED = original


class TestKillSwitch:
    def test_kill_switch_off_exits_without_any_read(self):
        settings.PROMOS_WRITE_ENABLED = False

        with (
            patch.object(sync_promo_prices, "get_mlwebhook_engine") as mock_engine,
            patch.object(sync_promo_prices, "get_background_db") as mock_get_db,
        ):
            sync_promo_prices.run_sync()

        mock_engine.assert_not_called()
        mock_get_db.assert_not_called()


class TestFetchNewlyActiveRows:
    def test_query_filters_by_watermark_and_active_status(self):
        fake_conn = MagicMock()
        fake_conn.execute.return_value.fetchall.return_value = [
            ("MLA1", datetime(2026, 1, 3, tzinfo=UTC)),
        ]
        fake_engine = MagicMock()
        fake_engine.connect.return_value.__enter__.return_value = fake_conn

        watermark = datetime(2026, 1, 1, tzinfo=UTC)
        with patch.object(sync_promo_prices, "get_mlwebhook_engine", return_value=fake_engine):
            rows = sync_promo_prices._fetch_newly_active_rows(watermark)

        assert rows == [("MLA1", datetime(2026, 1, 3, tzinfo=UTC))]
        # Exactly one query executed (batching, not per-item).
        assert fake_conn.execute.call_count == 1
        call_args = fake_conn.execute.call_args
        assert call_args[0][1] == {"watermark": watermark}
        query_text = str(call_args[0][0])
        assert "status IN ('candidate', 'started')" in query_text
        assert "updated_at" in query_text


class TestMapActivationByItem:
    def test_maps_mlas_to_item_ids_and_takes_max_updated_at(self, db):
        _make_producto(db, 2001)
        _make_publicacion(db, 2001, "MLA1")
        _make_publicacion(db, 2001, "MLA2")
        _make_producto(db, 2002)
        _make_publicacion(db, 2002, "MLA3")

        rows = [
            ("MLA1", datetime(2026, 1, 1, tzinfo=UTC)),
            ("MLA2", datetime(2026, 1, 3, tzinfo=UTC)),  # newer -> wins for item 2001
            ("MLA3", datetime(2026, 1, 2, tzinfo=UTC)),
        ]

        result = sync_promo_prices._map_activation_by_item(db, rows)

        assert result == {
            2001: datetime(2026, 1, 3, tzinfo=UTC),
            2002: datetime(2026, 1, 2, tzinfo=UTC),
        }

    def test_unmapped_mla_is_skipped(self, db):
        rows = [("MLA_UNKNOWN", datetime(2026, 1, 1, tzinfo=UTC))]
        result = sync_promo_prices._map_activation_by_item(db, rows)
        assert result == {}

    def test_empty_rows_no_query(self, db):
        result = sync_promo_prices._map_activation_by_item(db, [])
        assert result == {}


class TestRunSyncNoClobberManual:
    def test_recompute_called_with_activation_time_not_wallclock(self, db):
        _make_producto(db, 2001)
        _make_publicacion(db, 2001, "MLA1")
        activation_time = datetime(2026, 1, 3, tzinfo=UTC)

        with (
            patch.object(sync_promo_prices, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(
                sync_promo_prices,
                "_fetch_newly_active_rows",
                return_value=[("MLA1", activation_time)],
            ),
            patch.object(sync_promo_prices, "recompute_item") as mock_recompute,
        ):
            sync_promo_prices.run_sync()

        mock_recompute.assert_called_once_with(db, 2001, now=activation_time)

    def test_manual_edit_after_activation_is_not_overwritten(self, db):
        """End-to-end (real recompute_item): a manual edit made AFTER the
        promo activation time must survive the sync, per the no-clobber
        guard (design #937)."""
        _make_producto(db, 2001)
        _make_publicacion(db, 2001, "MLA1")
        pricing = ProductoPricing(item_id=2001, precio_lista_ml=1234.0)
        db.add(pricing)
        manual_fecha = datetime(2026, 1, 5, tzinfo=UTC)
        db.add(ProductoPrecioOrigen(item_id=2001, column_key="precio_lista_ml", origen="manual", fecha=manual_fecha))
        db.commit()

        activation_time = datetime(2026, 1, 2, tzinfo=UTC)  # before the manual edit

        with (
            patch.object(sync_promo_prices, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(
                sync_promo_prices,
                "_fetch_newly_active_rows",
                return_value=[("MLA1", activation_time)],
            ),
            patch(
                "app.services.promo_price_propagation.fetch_item_promotions",
                return_value=[{"promotion_id": "PROMO-A", "status": "started", "price": 700.0}],
            ),
        ):
            sync_promo_prices.run_sync()

        db.commit()
        pricing = db.query(ProductoPricing).filter_by(item_id=2001).first()
        assert float(pricing.precio_lista_ml) == 1234.0  # unchanged: manual wins
        origen = db.query(ProductoPrecioOrigen).filter_by(item_id=2001, column_key="precio_lista_ml").first()
        assert origen.origen == "manual"


def _fake_ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return _Ctx()


class TestWatermarkAdvance:
    def test_watermark_advances_only_after_success(self, db):
        _make_producto(db, 2001)
        _make_publicacion(db, 2001, "MLA1")
        activation_time = datetime(2026, 1, 3, tzinfo=UTC)

        with (
            patch.object(sync_promo_prices, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(
                sync_promo_prices,
                "_fetch_newly_active_rows",
                return_value=[("MLA1", activation_time)],
            ),
            patch.object(sync_promo_prices, "recompute_item") as mock_recompute,
        ):
            sync_promo_prices.run_sync()

        mock_recompute.assert_called_once()
        db.commit()
        stored = get_watermark(db)
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=UTC)
        assert stored == activation_time

    def test_watermark_not_advanced_when_an_item_fails(self, db):
        _make_producto(db, 2001)
        _make_publicacion(db, 2001, "MLA1")
        _make_producto(db, 2002)
        _make_publicacion(db, 2002, "MLA2")
        t1 = datetime(2026, 1, 3, tzinfo=UTC)
        t2 = datetime(2026, 1, 4, tzinfo=UTC)

        def fake_recompute(db_arg, item_id, *, now=None):
            if item_id == 2002:
                raise RuntimeError("cross-db outage")

        with (
            patch.object(sync_promo_prices, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(
                sync_promo_prices,
                "_fetch_newly_active_rows",
                return_value=[("MLA1", t1), ("MLA2", t2)],
            ),
            patch.object(sync_promo_prices, "recompute_item", side_effect=fake_recompute) as mock_recompute,
        ):
            sync_promo_prices.run_sync()

        db.commit()
        # Both items were attempted (isolated failure — other items still processed).
        assert mock_recompute.call_count == 2
        assert get_watermark(db) is None  # NOT advanced past the failed item


class TestIdempotentEmptyRun:
    def test_no_newly_active_rows_no_writes_watermark_unchanged(self, db):
        with (
            patch.object(sync_promo_prices, "get_background_db", side_effect=lambda: _fake_ctx(db)),
            patch.object(sync_promo_prices, "_fetch_newly_active_rows", return_value=[]),
            patch.object(sync_promo_prices, "recompute_item") as mock_recompute,
        ):
            sync_promo_prices.run_sync()

        mock_recompute.assert_not_called()
        db.commit()
        assert get_watermark(db) is None
