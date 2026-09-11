"""Tests for the frozen cost snapshot writer (ml-ventas-modo-logistico, PR3).

The single invariant every test here protects: a re-ingestion of an order
NEVER rewrites an already-frozen `ml_order_item_costos` row, even when the
ERP cost/IVA/exchange rate that produced it has since changed. Every
mutation-verified test in this file is written to FAIL if that invariant is
silently broken (e.g. swapping `ON CONFLICT DO NOTHING` for an UPDATE, or
letting a `coalesce(..., 0)` stand in for "unknown").
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.producto import ProductoERP, TipoMoneda
from app.models.publicacion_ml import PublicacionML
from app.models.tipo_cambio import TipoCambio
from app.services.ml_orders_ingestion.costeo_service import congelar
from app.services.ml_orders_ingestion.mapper import OrderItemOpsDTO


def _item(
    item_id: str = "MLA1",
    variation_id=None,
    seller_sku: str = "SKU-1",
    unit_price: float = 1000.0,
) -> OrderItemOpsDTO:
    return OrderItemOpsDTO(
        item_id=item_id,
        variation_id=variation_id,
        seller_sku=seller_sku,
        title="Producto de prueba",
        quantity=1,
        unit_price=unit_price,
        full_unit_price=unit_price,
        sale_fee=0.0,
        listing_type_id="gold_special",
    )


def _producto(db, item_id: int = 500, costo: float = 100.0, iva: float = 21.0, moneda=TipoMoneda.ARS) -> ProductoERP:
    producto = ProductoERP(
        item_id=item_id,
        codigo="SKU-1",
        descripcion="Producto de prueba",
        costo=costo,
        moneda_costo=moneda,
        iva=iva,
    )
    db.add(producto)
    db.flush()
    return producto


def _publicacion(db, mla: str = "MLA1", item_id: int = 500) -> PublicacionML:
    publicacion = PublicacionML(mla=mla, item_id=item_id, activo=True)
    db.add(publicacion)
    db.flush()
    return publicacion


class TestReingestionNeverRewrites:
    def test_reingestion_never_rewrites_frozen_snapshot(self, db):
        """MUTATION-VERIFIED: replacing `on_conflict_do_nothing` with
        `on_conflict_do_update` in `costeo_service._insert_stmt` call site
        makes this test fail -- the second `congelar()` call would pick up
        the mutated `costo` instead of the frozen one."""
        producto = _producto(db, costo=100.0)
        _publicacion(db)
        db.commit()

        congelar(db, order_id=111, items=[_item()])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=111, item_id="MLA1").one()
        assert row.costo_unitario_ars == Decimal("100.0000")

        producto.costo = 999.0
        db.add(producto)
        db.commit()

        congelar(db, order_id=111, items=[_item()])
        db.commit()

        row_again = db.query(MlOrderItemCosto).filter_by(order_id=111, item_id="MLA1").one()
        assert row_again.costo_unitario_ars == Decimal("100.0000")

    def test_reingestion_never_rewrites_frozen_iva_rate(self, db):
        """Same pattern for `iva_pct` -- a later change to
        `productos_erp.iva` must not leak into an already-frozen snapshot."""
        producto = _producto(db, iva=21.0)
        _publicacion(db)
        db.commit()

        congelar(db, order_id=222, items=[_item()])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=222, item_id="MLA1").one()
        assert row.iva_pct == Decimal("21.00")

        producto.iva = 10.5
        db.add(producto)
        db.commit()

        congelar(db, order_id=222, items=[_item()])
        db.commit()

        row_again = db.query(MlOrderItemCosto).filter_by(order_id=222, item_id="MLA1").one()
        assert row_again.iva_pct == Decimal("21.00")

    def test_new_order_item_stamped_on_first_insert(self, db):
        _producto(db, costo=250.5, iva=10.5)
        _publicacion(db)
        db.commit()

        congelar(db, order_id=333, items=[_item(unit_price=1234.56)])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=333, item_id="MLA1").one()
        assert row.costo_origen == Decimal("250.5")
        assert row.moneda == "ARS"
        assert row.iva_pct == Decimal("10.50")
        assert row.precio_unitario == Decimal("1234.56")
        assert row.producto_item_id == 500
        assert row.congelado_at is not None


class TestUsdExchangeRateFrozen:
    def test_usd_product_survives_later_rate_change(self, db):
        """R1 and R2 are constructed with explicit UTC-aware effective
        dates -- the frozen value must be the rate CAPTURED at snapshot
        time, never re-derived later."""
        _producto(db, costo=10.0, iva=21.0, moneda=TipoMoneda.USD)
        _publicacion(db)
        r1 = TipoCambio(fecha=date(2026, 9, 1), moneda="USD", compra=900.0, venta=950.0)
        db.add(r1)
        db.commit()

        congelar(db, order_id=444, items=[_item()])
        db.commit()

        row = db.query(MlOrderItemCosto).filter_by(order_id=444, item_id="MLA1").one()
        assert row.tipo_cambio == Decimal("950.0")
        assert row.costo_unitario_ars == Decimal("9500.0")

        # A later, higher rate arrives -- must NOT change the frozen row.
        r2 = TipoCambio(fecha=date(2026, 9, 10), moneda="USD", compra=1100.0, venta=1200.0)
        db.add(r2)
        db.commit()

        congelar(db, order_id=444, items=[_item()])
        db.commit()

        row_again = db.query(MlOrderItemCosto).filter_by(order_id=444, item_id="MLA1").one()
        assert row_again.tipo_cambio == Decimal("950.0")
        assert row_again.costo_unitario_ars == Decimal("9500.0")


class TestUnknownIsNotZero:
    def test_unmatched_product_is_unknown_not_zero(self, db):
        """MUTATION-VERIFIED: substituting a `coalesce(costo, 0)` for the
        None-check in `_resolve_cost` would write a `costo_unitario_ars=0`
        row here instead of writing NOTHING."""
        # No PublicacionML, no ProductoERP with a matching sku either.
        congelar(db, order_id=555, items=[_item(seller_sku="NO-MATCH")])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=555).count() == 0

    def test_missing_costo_is_unknown_not_zero(self, db):
        _producto(db, costo=None, iva=21.0)
        _publicacion(db)
        db.commit()

        congelar(db, order_id=666, items=[_item()])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=666).count() == 0

    def test_unlinked_publication_is_unknown_not_zero(self, db):
        """No `PublicacionML` row at all, and the SKU fallback also
        doesn't match -- unknown, no row."""
        congelar(db, order_id=777, items=[_item(seller_sku="ANOTHER-SKU")])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=777).count() == 0

    def test_product_resolves_iva_does_not_is_unknown_whole(self, db):
        """Cost resolves, IVA does not -- the WHOLE snapshot is unknown,
        never a half-written row."""
        producto = _producto(db, costo=100.0)
        _publicacion(db)
        db.commit()
        # `ProductoERP.iva` has a Python-side `default=21.0` that fires at
        # INSERT time even when explicitly constructed with `iva=None` --
        # an UPDATE bypasses that default, giving a real NULL in the DB.
        db.query(ProductoERP).filter(ProductoERP.item_id == producto.item_id).update({"iva": None})
        db.commit()

        congelar(db, order_id=888, items=[_item()])
        db.commit()

        assert db.query(MlOrderItemCosto).filter_by(order_id=888).count() == 0


class TestDialectAwareInsert:
    def test_sqlite_postgres_on_conflict_do_nothing_dialect_path(self, db):
        """Verifies the dialect-aware `_insert_stmt` path actually executes
        `ON CONFLICT DO NOTHING` under SQLite (the test DB's dialect) --
        i.e. a second `congelar()` call for the same key does not raise a
        uniqueness violation and does not change the row."""
        assert db.bind.dialect.name == "sqlite"

        _producto(db, costo=42.0, iva=21.0)
        _publicacion(db)
        db.commit()

        congelar(db, order_id=999, items=[_item()])
        db.commit()
        congelar(db, order_id=999, items=[_item()])
        db.commit()

        rows = db.query(MlOrderItemCosto).filter_by(order_id=999, item_id="MLA1").all()
        assert len(rows) == 1
        assert rows[0].costo_unitario_ars == Decimal("42.0000")
