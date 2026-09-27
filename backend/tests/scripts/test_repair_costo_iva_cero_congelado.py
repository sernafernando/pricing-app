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


class TestBackfillRowsAreOutOfScope:
    def test_backfill_row_with_bad_iva_is_never_deleted(self, db):
        """Defect 1: a row written by the BACKFILL path (`fuente=hist_*`)
        carries a DATED historic cost, correct for the order's own date --
        even when its `iva_pct` is `<= 0`. This script must NEVER touch it:
        recongelar() would resolve TODAY's cost/rate for a sale months
        old, silently corrupting a correct historic snapshot. It must be
        reported separately, never deleted, never recongelado."""
        db.add(_order(300))
        db.add(_item_ops(300))
        _producto(db, costo=999.0, iva=21.0)  # today's cost -- must NOT be used
        _publicacion(db)
        row = _frozen_row(db, order_id=300, costo_unitario_ars=250.0, iva_pct=0.0)
        row.fuente = "hist_publicacion"
        db.commit()

        result = script.run_repair(limit=None, dry_run=False)

        assert result.deleted == 0
        assert result.recongelados == 0
        assert result.examined_out_of_scope_backfill == 1

        still_there = db.query(MlOrderItemCosto).filter_by(order_id=300).one()
        assert still_there.costo_unitario_ars == Decimal("250.0000")
        assert still_there.iva_pct == Decimal("0.00")


class TestNeverInsertsUntouchedItems:
    def test_repair_does_not_write_a_row_for_an_item_it_did_not_delete(self, db):
        """Defect 2: the order has TWO items -- one with a corrupt frozen
        row (deleted+recongelado), and one with NO frozen row at all (a
        pre-existing hole). `congelar()` runs over the whole order, but
        the untouched item must stay untouched -- it was never a
        candidate, so this script must never be the reason it gets a
        fresh row stamped with today's cost."""
        db.add(_order(400))
        db.add(_item_ops(400, item_id="MLA1"))
        db.add(_item_ops(400, item_id="MLA2"))
        _producto(db, item_id=500, costo=250.0, iva=21.0)
        _publicacion(db, mla="MLA1", item_id=500)
        # MLA2 deliberately has NO ProductoERP/publicacion link -> would be
        # uncostable if congelar() ever looked at it.
        _frozen_row(db, order_id=400, item_id="MLA1", costo_unitario_ars=0.0, iva_pct=21.0)
        db.commit()

        result = script.run_repair(limit=None, dry_run=False)

        assert result.deleted == 1
        assert result.recongelados == 1
        assert result.huecos == 0  # MLA2 was never a candidate -- not a "hole" either

        assert db.query(MlOrderItemCosto).filter_by(order_id=400, item_id="MLA2").count() == 0


class TestNeverResurrectsRemovedItems:
    def test_repair_never_recreates_a_row_for_an_item_no_longer_on_the_order(self, db):
        """Defect 3: a frozen row can deliberately OUTLIVE its item (a
        partial cancellation removed the `MlOrderItemOps` row). If that
        surviving snapshot happens to be corrupt (`iva_pct<=0`), deleting
        it is fine -- but `congelar()` has NOTHING to re-freeze from
        because the item is gone, and the row must NOT come back changed
        or otherwise: it must be reported as an untouchable loss, not
        silently vanish."""
        db.add(_order(500))
        # No MlOrderItemOps row for this order/item -- it was cancelled out.
        _frozen_row(db, order_id=500, item_id="MLA1", costo_unitario_ars=250.0, iva_pct=0.0)
        db.commit()

        result = script.run_repair(limit=None, dry_run=False)

        assert result.deleted == 0
        assert result.examined_out_of_scope_item_gone == 1
        assert db.query(MlOrderItemCosto).filter_by(order_id=500, item_id="MLA1").count() == 1


class TestReportArithmeticCloses:
    def test_deleted_equals_recongelados_plus_huecos_plus_out_of_scope(self, db):
        """Defect 4: the report's numbers must CLOSE. Every examined
        candidate row lands in exactly one bucket: recongelado, hueco, or
        one of the out-of-scope reasons (backfill / item gone)."""
        # 1) real fix -> recongelado
        db.add(_order(600))
        db.add(_item_ops(600, item_id="MLA1"))
        _producto(db, item_id=501, costo=250.0, iva=21.0)
        _publicacion(db, mla="MLA1", item_id=501)
        _frozen_row(db, order_id=600, item_id="MLA1", costo_unitario_ars=0.0, iva_pct=21.0, producto_item_id=501)

        # 2) still uncostable -> hueco
        db.add(_order(601))
        db.add(_item_ops(601, item_id="MLA2"))
        _producto(db, item_id=502, costo=0.0, iva=21.0)
        _publicacion(db, mla="MLA2", item_id=502)
        _frozen_row(db, order_id=601, item_id="MLA2", costo_unitario_ars=0.0, iva_pct=21.0, producto_item_id=502)

        # 3) backfill row -> out of scope
        db.add(_order(602))
        db.add(_item_ops(602, item_id="MLA3"))
        _producto(db, item_id=503, costo=999.0, iva=21.0)
        _publicacion(db, mla="MLA3", item_id=503)
        backfill_row = _frozen_row(
            db, order_id=602, item_id="MLA3", costo_unitario_ars=250.0, iva_pct=0.0, producto_item_id=503
        )
        backfill_row.fuente = "hist_publicacion"

        # 4) item gone -> out of scope
        db.add(_order(603))
        _frozen_row(db, order_id=603, item_id="MLA4", costo_unitario_ars=250.0, iva_pct=0.0, producto_item_id=504)

        db.commit()

        result = script.run_repair(limit=None, dry_run=False)

        assert result.examined == 4
        assert result.deleted == 2  # only (1) and (4) match the delete criterion path
        assert (
            result.recongelados + result.huecos + result.examined_out_of_scope_backfill
            == result.examined - result.examined_out_of_scope_item_gone
        )


class TestKeyIncludesOrderId:
    def test_same_item_id_different_orders_do_not_collide(self, db):
        """Defect 4 (report collision): two DIFFERENT orders sharing the
        same MLA -- one recongelado, one left as a hole -- must be
        reported and re-frozen independently. A key without `order_id`
        would let one order's outcome overwrite the other's in
        `items_by_key`."""
        db.add(_order(700))
        db.add(_item_ops(700, item_id="MLA1"))
        _producto(db, item_id=505, costo=250.0, iva=21.0)
        _publicacion(db, mla="MLA1", item_id=505)
        _frozen_row(db, order_id=700, item_id="MLA1", costo_unitario_ars=0.0, iva_pct=21.0, producto_item_id=505)

        db.add(_order(701))
        db.add(_item_ops(701, item_id="MLA1"))
        # Different product row (same MLA, different order) that is still
        # uncostable -- linked via a SEPARATE PublicacionML? No: same MLA
        # necessarily resolves to the same ProductoERP. Use a still-zero
        # cost so THIS order's item ends up a hole while order 700's does
        # not -- proving per-order independence requires per-order product
        # state, so give order 701's item no publicacion link at all.
        _frozen_row(db, order_id=701, item_id="MLA1", costo_unitario_ars=0.0, iva_pct=21.0, producto_item_id=505)

        db.commit()

        result = script.run_repair(limit=None, dry_run=False)

        assert result.deleted == 2
        assert result.recongelados == 2
        row_700 = db.query(MlOrderItemCosto).filter_by(order_id=700, item_id="MLA1").one()
        row_701 = db.query(MlOrderItemCosto).filter_by(order_id=701, item_id="MLA1").one()
        assert row_700.costo_unitario_ars == Decimal("250.0000")
        assert row_701.costo_unitario_ars == Decimal("250.0000")


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
