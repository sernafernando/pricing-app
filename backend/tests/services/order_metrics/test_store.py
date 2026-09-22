"""RED/GREEN -- `recompute_order_metrics` upserts `ml_order_metrics` +
`ml_venta_deducciones` + the legacy `ml_orders_ops.total_gauss*` columns, and
never commits -- the caller controls the transaction (ventas-ml-rediseno
PR1.T7, design D2, D7).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentOps
from app.models.ml_venta_deduccion import MlVentaDeduccion
from app.models.varios_venta_pct import VariosVentaPct
from app.services.order_metrics.compute import compute_order_metrics
from app.services.order_metrics.store import recompute_order_metrics
from app.services.order_metrics.types import GaussStatus


def _order(db, order_id: int, shipping_id=None) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            date_created=datetime(2026, 8, 15, tzinfo=timezone.utc),
            seller_id=999,
            shipping_id=shipping_id,
        )
    )


def _varios(db, porcentaje="0.00") -> None:
    """A baseline "% de varios" version covering everything -- same fixture
    as `test_compute.py`'s own `_varios`, so a base value the tests are not
    exercising never accidentally becomes the thing under test."""
    db.add(VariosVentaPct(porcentaje=Decimal(porcentaje), fecha_desde=date(2020, 1, 1), fecha_hasta=None))


def _item_with_cost(db, order_id: int, item_id: str, quantity: int, costo_unitario_ars: Decimal) -> None:
    db.add(MlOrderItemOps(order_id=order_id, item_id=item_id, seller_sku="SKU-1", quantity=quantity))
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id=item_id,
            costo_origen=costo_unitario_ars,
            moneda="ARS",
            costo_unitario_ars=costo_unitario_ars,
            iva_pct=Decimal("21.00"),
            precio_unitario=Decimal("100.00"),
            fuente="sku",
            producto_item_id=1,
        )
    )


class TestRecomputeOrderMetricsUpserts:
    def test_inserts_metrics_row_and_legacy_columns_no_commit(self, db) -> None:
        order_id = 6001
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()

        result = recompute_order_metrics(db, [order_id])
        # No commit inside recompute_order_metrics -- flush is enough for a
        # same-session read to see the row.
        db.flush()

        row = db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).one()
        assert row.total_gauss == result[order_id].total_gauss
        assert row.gauss_status == result[order_id].gauss_status.value
        assert row.formula_version == result[order_id].formula_version

        order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).one()
        assert order.total_gauss == result[order_id].total_gauss
        assert order.total_gauss_stale is False
        assert order.total_gauss_at is not None

        deduccion_rows = db.query(MlVentaDeduccion).filter(MlVentaDeduccion.order_id == order_id).all()
        assert any(r.code == "costo_mercaderia" for r in deduccion_rows)

        db.rollback()

    def test_second_call_updates_the_same_row_instead_of_duplicating(self, db) -> None:
        order_id = 6002
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()

        recompute_order_metrics(db, [order_id])
        db.commit()

        recompute_order_metrics(db, [order_id])
        db.commit()

        rows = db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).all()
        assert len(rows) == 1

    def test_empty_order_ids_returns_empty_dict(self, db) -> None:
        assert recompute_order_metrics(db, []) == {}

    def test_unknown_order_id_is_skipped_never_inserted(self, db) -> None:
        # `ml_order_metrics.order_id` has a hard FK to `ml_orders_ops` --
        # an id with no `ml_orders_ops` row must never reach `db.add`, or
        # the flush aborts the WHOLE batch, including the real order.
        order_id = 6003
        unknown_id = 999998
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()

        result = recompute_order_metrics(db, [unknown_id, order_id])
        db.flush()  # SQLite does not enforce the FK here; the assertions below prove the skip

        assert unknown_id not in result
        assert order_id in result
        assert db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == unknown_id).one_or_none() is None
        assert db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).one_or_none() is not None


class TestRecomputeOrderMetricsRefreshesTheSession:
    """Core INSERT/DELETE bypass the identity map. `persistir_total_gauss`
    is an alias of this writer, so a caller that already read these rows in
    the SAME transaction must not keep seeing the values from before."""

    def test_a_row_read_before_the_recompute_is_not_stale_afterwards(self, db) -> None:
        order_id = 6010
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()
        recompute_order_metrics(db, [order_id])
        db.commit()

        # Read BEFORE the second recompute, and keep the object around.
        fila = db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).one()
        deduccion = db.query(MlVentaDeduccion).filter(MlVentaDeduccion.order_id == order_id).first()
        assert deduccion is not None

        # The cost changes, so the stored numbers must change with it.
        db.query(MlOrderItemCosto).filter(MlOrderItemCosto.order_id == order_id).update(
            {"costo_unitario_ars": Decimal("80.00"), "costo_origen": Decimal("80.00")}
        )
        db.commit()

        recompute_order_metrics(db, [order_id])

        # No commit in between: the objects read above must already reflect
        # the new values, not the ones they were loaded with.
        assert fila.costo_mercaderia == Decimal("80.00")
        assert deduccion.monto == Decimal("80.00")


class TestRecomputeOrderMetricsUpdatesValues:
    def test_a_changed_input_overwrites_the_stored_numbers(self, db) -> None:
        # Guards the ON CONFLICT *DO UPDATE*: with DO NOTHING (or an empty
        # `set_`) the row would silently keep its first-computed values and
        # a "one row only" assertion would still pass.
        order_id = 6011
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()
        recompute_order_metrics(db, [order_id])
        db.commit()
        primero = db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).one().costo_mercaderia

        db.query(MlOrderItemCosto).filter(MlOrderItemCosto.order_id == order_id).update(
            {"costo_unitario_ars": Decimal("80.00"), "costo_origen": Decimal("80.00")}
        )
        db.commit()
        recompute_order_metrics(db, [order_id])
        db.commit()

        fila = db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).one()
        assert primero == Decimal("10.00")
        assert fila.costo_mercaderia == Decimal("80.00")
        deduccion = (
            db.query(MlVentaDeduccion)
            .filter(MlVentaDeduccion.order_id == order_id, MlVentaDeduccion.code == "costo_mercaderia")
            .one()
        )
        assert deduccion.monto == Decimal("80.00")


class TestRecomputeOrderMetricsStoresRealFormulaOutput:
    """`recompute_order_metrics` must store what `compute_order_metrics`
    actually computed for a GENUINELY resolved order -- not just an
    unresolved one, which `TestRecomputeOrderMetricsUpserts` above already
    covers and which stores `None`/`unresolved` almost for free."""

    def test_ok_order_stores_total_gauss_and_markup_matching_compute(self, db) -> None:
        order_id = 6010
        _order(db, order_id, shipping_id=6810)
        db.add(MlShipmentOps(shipment_id=6810, logistic_type="self_service"))
        db.add(Logistica(id=61, nombre="Andreani"))
        db.add(
            EtiquetaEnvio(
                shipping_id="6810", fecha_envio=date(2026, 8, 16), logistica_id=61, costo_override=Decimal("50.00")
            )
        )
        # `precio_unitario=100.00` (fixed in `_item_with_cost`) * quantity 2
        # == the payment's `net_received_amount` below -- must reconcile
        # exactly, or `descomponer_neto` reports `neto_sin_iva=None` and the
        # order can never reach `GaussStatus.OK`.
        _item_with_cost(db, order_id, "MLA1", 2, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("200.00")
            )
        )
        _varios(db)
        db.commit()

        # The fixture itself must land on the OK branch -- an assertion
        # nested under "if it happens to be OK" can pass vacuously if the
        # fixture stops reconciling.
        expected = compute_order_metrics(db, [order_id])[order_id]
        assert expected.gauss_status == GaussStatus.OK
        assert expected.total_gauss is not None
        assert expected.markup_pct is not None

        result = recompute_order_metrics(db, [order_id])
        db.flush()

        stored = result[order_id]
        assert stored.total_gauss == expected.total_gauss
        assert stored.markup_pct == expected.markup_pct
        assert stored.gauss_status == expected.gauss_status
        assert stored.lineas == expected.lineas
        assert stored.formula_version == expected.formula_version

        row = db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).one()
        assert row.total_gauss == expected.total_gauss
        assert row.markup_pct == expected.markup_pct
        assert row.gauss_status == GaussStatus.OK.value
        assert row.formula_version == expected.formula_version
        assert row.computed_at is not None

        order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).one()
        assert order.total_gauss == expected.total_gauss
        assert order.total_gauss_stale is False
        assert order.total_gauss_provisional is False

        db.rollback()

    def test_provisional_order_stores_provisional_status_and_total(self, db) -> None:
        # Same fixture as `test_compute.py::test_provisional_order_status_
        # and_falta`: `self_service` shipment with a `shipping_id` but no
        # `EtiquetaEnvio` -- the Flex cost is not resolvable YET, which is
        # the DELIBERATE provisional exception, not the generic "unresolved"
        # path.
        order_id = 6011
        _order(db, order_id, shipping_id=6811)
        db.add(MlShipmentOps(shipment_id=6811, logistic_type="self_service"))
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        _varios(db)
        db.commit()

        expected = compute_order_metrics(db, [order_id])[order_id]
        assert expected.gauss_status == GaussStatus.PROVISIONAL
        assert expected.total_gauss is not None

        result = recompute_order_metrics(db, [order_id])
        db.flush()

        stored = result[order_id]
        assert stored.total_gauss == expected.total_gauss
        assert stored.markup_pct == expected.markup_pct
        assert stored.gauss_status == expected.gauss_status
        assert stored.lineas == expected.lineas
        assert stored.formula_version == expected.formula_version

        row = db.query(MlOrderMetrics).filter(MlOrderMetrics.order_id == order_id).one()
        assert row.gauss_status == GaussStatus.PROVISIONAL.value
        assert row.total_gauss == expected.total_gauss
        assert row.provisional_falta == expected.provisional_falta

        order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).one()
        assert order.total_gauss_provisional is True
        assert order.total_gauss == expected.total_gauss

        db.rollback()

    def test_deduction_that_no_longer_applies_is_deleted_on_recompute(self, db) -> None:
        # First pass: `self_service` + a resolvable Flex cost -- `envio_flex`
        # APPLIES and is stored. Second pass: the order is no longer
        # `self_service` (switched to `cross_docking`) -- `envio_flex` no
        # longer applies at all (not merely unresolved), and the STALE row
        # from the first pass must be deleted, never left carrying a
        # freight cost that is no longer owed (store.py's own rule, mirrored
        # from `persistir_total_gauss`).
        order_id = 6012
        _order(db, order_id, shipping_id=6812)
        db.add(MlShipmentOps(shipment_id=6812, logistic_type="self_service"))
        db.add(Logistica(id=62, nombre="Andreani"))
        db.add(
            EtiquetaEnvio(
                shipping_id="6812", fecha_envio=date(2026, 8, 16), logistica_id=62, costo_override=Decimal("30.00")
            )
        )
        _item_with_cost(db, order_id, "MLA1", 2, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("200.00")
            )
        )
        _varios(db)
        db.commit()

        recompute_order_metrics(db, [order_id])
        db.commit()

        rows_before = db.query(MlVentaDeduccion).filter(MlVentaDeduccion.order_id == order_id).all()
        codes_before = {r.code for r in rows_before}
        assert "envio_flex" in codes_before, "fixture must actually apply envio_flex before it can prove deletion"

        # Flip the shipment out of `self_service` -- `EnvioFlexDeduccion`
        # returns no key at all for this order now (not applicable).
        shipment = db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id == 6812).one()
        shipment.logistic_type = "cross_docking"
        db.commit()

        recompute_order_metrics(db, [order_id])
        db.commit()

        rows_after = db.query(MlVentaDeduccion).filter(MlVentaDeduccion.order_id == order_id).all()
        codes_after = {r.code for r in rows_after}
        assert "envio_flex" not in codes_after
        assert "costo_mercaderia" in codes_after  # unrelated rows survive untouched

        db.rollback()
