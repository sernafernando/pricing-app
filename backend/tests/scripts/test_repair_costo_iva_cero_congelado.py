"""Tests for the frozen-cost-zero/IVA-zero repair script
(fix/costeo-iva-cero-y-pase-correctivo, Parte 1b pase correctivo).

The single invariant this script exists to protect: a frozen row whose
`costo_unitario_ars` or `iva_pct` is `<= 0` is corruption from before the
zero-guard shipped, never a real snapshot -- it must be deleted and
re-`congelar()`-ed, and an item that STILL cannot be costed under current
rules must be left as a visible hole, never re-frozen with another zero.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.producto import ProductoERP, TipoMoneda
from app.models.publicacion_ml import PublicacionML
from app.scripts import repair_costo_iva_cero_congelado as script


@pytest.fixture(autouse=True)
def _session_local(db, monkeypatch):
    """Same pattern `test_backfill_costo_congelado.py` uses: the script
    opens its OWN `SessionLocal()` (CLI entry point) -- point it at the
    test's in-memory sqlite session, with a no-op `.close()` so the
    fixture-owned session survives the call."""

    class _NoCloseSession:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def close(self):
            pass

    wrapped = _NoCloseSession(db)
    monkeypatch.setattr(script, "SessionLocal", lambda: wrapped)


def _order(order_id: int, seller_id: int = 1) -> MlOrdersOps:
    now = datetime.now(timezone.utc)
    return MlOrdersOps(order_id=order_id, seller_id=seller_id, date_created=now, ml_last_updated=now)


def _item_ops(order_id: int, item_id: str = "MLA1", unit_price: float = 1000.0) -> MlOrderItemOps:
    return MlOrderItemOps(
        order_id=order_id,
        item_id=item_id,
        variation_id=None,
        seller_sku="SKU-1",
        title="Producto de prueba",
        quantity=1,
        unit_price=unit_price,
    )


def _producto(db, item_id: int = 500, costo: float = 100.0, iva: float = 21.0) -> ProductoERP:
    producto = ProductoERP(
        item_id=item_id,
        codigo="SKU-1",
        descripcion="Producto de prueba",
        costo=costo,
        moneda_costo=TipoMoneda.ARS,
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


def _frozen_row(
    db,
    order_id: int,
    item_id: str = "MLA1",
    costo_unitario_ars: float = 0.0,
    iva_pct: float = 21.0,
    producto_item_id: int = 500,
) -> MlOrderItemCosto:
    row = MlOrderItemCosto(
        order_id=order_id,
        item_id=item_id,
        variation_id=None,
        costo_origen=Decimal(str(costo_unitario_ars)),
        moneda="ARS",
        costo_unitario_ars=Decimal(str(costo_unitario_ars)),
        iva_pct=Decimal(str(iva_pct)),
        precio_unitario=Decimal("1000.00"),
        fuente="erp_publicacion",
        producto_item_id=producto_item_id,
    )
    db.add(row)
    db.flush()
    return row


class TestHappyPathRecongela:
    def test_zero_cost_row_deleted_and_recongelado_with_real_cost(self, db):
        """A frozen row corrupted with `costo_unitario_ars=0` (the
        pre-guard bug) gets deleted, and the item -- whose linked product
        NOW has a real cost -- gets a fresh, correct row."""
        db.add(_order(100))
        db.add(_item_ops(100))
        _producto(db, costo=250.0, iva=21.0)
        _publicacion(db)
        _frozen_row(db, order_id=100, costo_unitario_ars=0.0, iva_pct=21.0)
        db.commit()

        result = script.run_repair(limit=None, dry_run=False)

        assert result.examined == 1
        assert result.deleted == 1
        assert result.recongelados == 1
        assert result.huecos == 0
        assert result.motivos_borrado[script.MOTIVO_COSTO_CERO] == 1

        row = db.query(MlOrderItemCosto).filter_by(order_id=100, item_id="MLA1").one()
        assert row.costo_unitario_ars == Decimal("250.0000")
        assert row.iva_pct == Decimal("21.00")

    def test_zero_iva_row_deleted_and_recongelado(self, db):
        """Same repair, but the corruption was `iva_pct=0` instead of the
        cost -- counted under its own separate reason."""
        db.add(_order(101))
        db.add(_item_ops(101))
        _producto(db, costo=250.0, iva=10.5)
        _publicacion(db)
        _frozen_row(db, order_id=101, costo_unitario_ars=250.0, iva_pct=0.0)
        db.commit()

        result = script.run_repair(limit=None, dry_run=False)

        assert result.deleted == 1
        assert result.recongelados == 1
        assert result.motivos_borrado[script.MOTIVO_IVA_CERO] == 1

        row = db.query(MlOrderItemCosto).filter_by(order_id=101, item_id="MLA1").one()
        assert row.iva_pct == Decimal("10.50")

    def test_dry_run_deletes_nothing(self, db):
        db.add(_order(102))
        db.add(_item_ops(102))
        _producto(db, costo=250.0, iva=21.0)
        _publicacion(db)
        _frozen_row(db, order_id=102, costo_unitario_ars=0.0, iva_pct=21.0)
        db.commit()

        result = script.run_repair(limit=None, dry_run=True)

        assert result.examined == 1
        assert result.deleted == 1  # reported as "would delete"
        assert db.query(MlOrderItemCosto).filter_by(order_id=102).count() == 1

    def test_the_command_line_default_deletes_nothing(self, db):
        """This script DELETES, unlike its INSERT-only sibling backfill, so
        the safe mode is the DEFAULT and destruction is opt-in via `--apply`.
        Pinning it here because a safety default with no test is a default
        someone inverts by accident: calling `main` with NO arguments must
        leave the row on disk."""
        db.add(_order(103))
        db.add(_item_ops(103))
        _producto(db, costo=250.0, iva=21.0)
        _publicacion(db)
        _frozen_row(db, order_id=103, costo_unitario_ars=0.0, iva_pct=21.0)
        db.commit()

        script.main([])

        # Assert the VALUE, not the count: the repair deletes and re-inserts,
        # so a count of 1 is what you get either way and would prove nothing.
        # The zero has to still BE there.
        filas = db.query(MlOrderItemCosto).filter_by(order_id=103).all()
        assert len(filas) == 1
        assert float(filas[0].costo_unitario_ars) == 0.0

    def test_apply_is_what_actually_deletes(self, db):
        """The mirror of the test above: the same call WITH `--apply` does
        delete, so the default is proven to be the only thing holding it
        back -- not a broken code path that never deletes at all."""
        db.add(_order(104))
        db.add(_item_ops(104))
        _producto(db, costo=250.0, iva=21.0)
        _publicacion(db)
        _frozen_row(db, order_id=104, costo_unitario_ars=0.0, iva_pct=21.0)
        db.commit()

        script.main(["--apply"])

        filas = db.query(MlOrderItemCosto).filter_by(order_id=104).all()
        assert len(filas) == 1
        assert float(filas[0].costo_unitario_ars) == 250.0


class TestUncostableHoleIsVisible:
    def test_item_still_uncostable_after_deletion_is_left_as_hole(self, db):
        """The linked product ALSO has no real cost under the current
        rules (still `<= 0`, and no combo composition) -- the item must be
        left WITHOUT a frozen row, never re-frozen with another zero."""
        db.add(_order(200))
        db.add(_item_ops(200))
        _producto(db, costo=0.0, iva=21.0)  # still an ERP hole today
        _publicacion(db)
        _frozen_row(db, order_id=200, costo_unitario_ars=0.0, iva_pct=21.0)
        db.commit()

        result = script.run_repair(limit=None, dry_run=False)

        assert result.deleted == 1
        assert result.recongelados == 0
        assert result.huecos == 1
        assert result.motivos_hueco[script.HUECO_SIN_COSTO_NI_COMBO] == 1

        assert db.query(MlOrderItemCosto).filter_by(order_id=200).count() == 0
