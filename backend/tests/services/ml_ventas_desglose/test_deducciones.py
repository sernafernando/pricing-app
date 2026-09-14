"""RED/GREEN -- Total Gauss deduction chain (ml-ventas-modo-logistico, PR5,
design D1/D2/D7).

`total_gauss` is `neto_sin_iva` minus every APPLICABLE deduction in
`DEDUCCIONES`, in order, entirely IVA-free. `None` propagates -- one
unresolved deduction makes the whole order's `total_gauss` unknown, never a
partial sum. Mutation-verified in the docstring of each test that names it.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps, MlShipmentOps
from app.models.ml_venta_deduccion import MlVentaDeduccion
from app.models.varios_venta_pct import VariosVentaPct
from app.services.ml_ventas_desglose.deducciones import (
    DEDUCCIONES,
    CostoMercaderiaDeduccion,
    EnvioFlexDeduccion,
    VariosDeduccion,
    calcular_total_gauss,
    marcar_stale,
    persistir_total_gauss,
)


def _order(db, order_id: int, shipping_id=None, date_created=None) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            date_created=date_created or datetime(2026, 8, 15, tzinfo=timezone.utc),
            seller_id=999,
            shipping_id=shipping_id,
        )
    )


def _item_with_cost(db, order_id, item_id, quantity, costo_unitario_ars) -> None:
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


def _item_no_cost(db, order_id, item_id, quantity=1) -> None:
    db.add(MlOrderItemOps(order_id=order_id, item_id=item_id, seller_sku="SKU-1", quantity=quantity))


def _varios(db, porcentaje="0.00") -> None:
    """A baseline "% de varios" version covering everything -- tests that
    are not ABOUT `VariosDeduccion` add this so it does not, itself, make
    every `total_gauss` unknown (an unconfigured rate is a legitimate
    unknown, exercised on its own in `TestVariosDeduccion`)."""
    db.add(VariosVentaPct(porcentaje=Decimal(porcentaje), fecha_desde=date(2020, 1, 1), fecha_hasta=None))


class TestRegistryOrderRespected:
    def test_chain_lineas_follow_orden(self, db) -> None:
        order_id = 1
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("50.00"))
        db.commit()

        result = calcular_total_gauss(db, [order_id], {order_id: Decimal("1000.00")})[order_id]

        codes = [code for code, _ in result.lineas]
        # `costo_mercaderia` (orden=1) is applicable here; `envio_flex`
        # (orden=2) is not (order is not self_service, no key returned).
        # Registry order is preserved regardless of which entries apply.
        assert codes == sorted(codes, key=lambda c: {d.code: d.orden for d in DEDUCCIONES}[c])
        assert "costo_mercaderia" in codes


class TestNonePropagatesNeverZero:
    def test_unresolved_deduction_makes_total_gauss_none_not_partial(self, db) -> None:
        """MUTATION: substituting the None check for `or 0` (a
        `coalesce`-style fallback) turns this into a $950 total instead of
        `None`, which must fail this test."""
        order_id = 2
        _order(db, order_id)
        _item_no_cost(db, order_id, "MLA1")  # no frozen cost -> CostoMercaderiaDeduccion returns None
        db.commit()

        result = calcular_total_gauss(db, [order_id], {order_id: Decimal("1000.00")})[order_id]

        assert result.total_gauss is None
        assert ("costo_mercaderia", None) in result.lineas


class TestOneUnresolvedItemBlocksOrderLevelCost:
    def test_partial_snapshot_is_unknown_not_partial_sum(self, db) -> None:
        """MUTATION: summing only the resolved items (ignoring the one
        without a snapshot) would return $50 instead of `None` -- that
        substitution must fail this test."""
        order_id = 3
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("50.00"))
        _item_no_cost(db, order_id, "MLA2")
        db.commit()

        result = CostoMercaderiaDeduccion().resolve_bulk(db, [order_id])

        assert result[order_id] is None


class TestFullyCostedOrderComputesTotalGauss:
    def test_happy_path(self, db) -> None:
        order_id = 4
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 2, Decimal("50.00"))
        _varios(db)
        db.commit()

        result = calcular_total_gauss(db, [order_id], {order_id: Decimal("1000.00")})[order_id]

        assert result.total_gauss == Decimal("900.00")  # 1000 - (50*2)
        assert ("costo_mercaderia", Decimal("100.00")) in result.lineas


class TestNoDeductionsTotalGaussEqualsNetoSinIva:
    def test_no_items_no_applicable_deductions(self, db) -> None:
        order_id = 5
        _order(db, order_id)
        db.commit()

        # No items at all: CostoMercaderiaDeduccion returns None (unknown),
        # so total_gauss is None too -- an order with nothing to cost is
        # not "zero deductions", it is unresolved.
        result = calcular_total_gauss(db, [order_id], {order_id: Decimal("500.00")})[order_id]
        assert result.total_gauss is None


class TestChainExtensibleNoHardcodedCount:
    def test_extra_resolver_applies_without_touching_orchestrator(self, db) -> None:
        order_id = 6
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        _varios(db)
        db.commit()

        class _ExtraFlatDeduccion:
            code = "extra_flat"
            concepto = "Extra"
            orden = 99
            base = "neto"
            es_porcentaje = False

            def resolve_bulk(self, db, order_ids):
                return {oid: Decimal("5.00") for oid in order_ids}

        import app.services.ml_ventas_desglose.deducciones as deducciones_module

        original = deducciones_module.DEDUCCIONES
        deducciones_module.DEDUCCIONES = original + (_ExtraFlatDeduccion(),)
        try:
            result = calcular_total_gauss(db, [order_id], {order_id: Decimal("100.00")})[order_id]
        finally:
            deducciones_module.DEDUCCIONES = original

        assert result.total_gauss == Decimal("100.00") - Decimal("10.00") - Decimal("5.00")
        assert ("extra_flat", Decimal("5.00")) in result.lineas


class TestEnvioFlexDeduccion:
    def test_not_applicable_when_not_self_service(self, db) -> None:
        order_id = 7
        _order(db, order_id, shipping_id=700)
        db.add(MlShipmentOps(shipment_id=700, logistic_type="cross_docking"))
        db.commit()

        result = EnvioFlexDeduccion().resolve_bulk(db, [order_id])

        assert order_id not in result

    def test_self_service_resolves_cost_via_costo_override(self, db) -> None:
        order_id = 8
        _order(db, order_id, shipping_id=800)
        db.add(MlShipmentOps(shipment_id=800, logistic_type="self_service"))
        db.add(Logistica(id=1, nombre="Andreani"))
        db.add(
            EtiquetaEnvio(
                shipping_id="800", fecha_envio=date(2026, 8, 1), logistica_id=1, costo_override=Decimal("300.00")
            )
        )
        db.commit()

        result = EnvioFlexDeduccion().resolve_bulk(db, [order_id])

        assert result[order_id] == Decimal("300.00")

    def test_self_service_unresolved_cost_is_none(self, db) -> None:
        """MUTATION: returning Decimal('0') instead of None for an
        unresolved Flex cost must fail this test."""
        order_id = 9
        _order(db, order_id, shipping_id=900)
        db.add(MlShipmentOps(shipment_id=900, logistic_type="self_service"))
        db.commit()  # no EtiquetaEnvio at all -> unresolved

        result = EnvioFlexDeduccion().resolve_bulk(db, [order_id])

        assert result[order_id] is None


class TestVariosDeduccion:
    def test_reads_version_in_force_at_sale_date(self, db) -> None:
        order_id = 10
        _order(db, order_id, date_created=datetime(2026, 6, 15, tzinfo=timezone.utc))
        db.add(VariosVentaPct(porcentaje=Decimal("2.50"), fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 5, 31)))
        db.add(VariosVentaPct(porcentaje=Decimal("3.00"), fecha_desde=date(2026, 6, 1), fecha_hasta=None))
        db.commit()

        result = VariosDeduccion().resolve_bulk(db, [order_id])

        assert result[order_id] == Decimal("3.00")

    def test_no_version_configured_is_unknown(self, db) -> None:
        order_id = 11
        _order(db, order_id)
        db.commit()

        result = VariosDeduccion().resolve_bulk(db, [order_id])

        assert result[order_id] is None

    def test_percentage_applies_over_neto_sin_iva(self, db) -> None:
        order_id = 12
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 0, Decimal("0.00"))  # no cost impact, isolates the % math
        db.add(VariosVentaPct(porcentaje=Decimal("2.00"), fecha_desde=date(2026, 1, 1), fecha_hasta=None))
        db.commit()

        result = calcular_total_gauss(db, [order_id], {order_id: Decimal("1000.00")})[order_id]

        assert ("varios", Decimal("20.00")) in result.lineas
        assert result.total_gauss == Decimal("980.00")


class TestPersistirTotalGauss:
    def test_stores_column_and_deduction_rows(self, db) -> None:
        from app.models.ml_payments import MlPaymentOps

        order_id = 13
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(MlPaymentOps(payment_id=13, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")))
        db.commit()

        persistir_total_gauss(db, [order_id])
        db.commit()

        order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).first()
        assert order.total_gauss_stale is False
        assert order.total_gauss_at is not None

        rows = db.query(MlVentaDeduccion).filter(MlVentaDeduccion.order_id == order_id).all()
        assert any(r.code == "costo_mercaderia" for r in rows)


class TestMarcarStale:
    def test_sets_stale_true_for_matching_shipping_id(self, db) -> None:
        order_id = 14
        _order(db, order_id, shipping_id=1400)
        db.commit()

        touched = marcar_stale(db, ["1400"])
        db.commit()

        order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).first()
        assert touched == 1
        assert order.total_gauss_stale is True

    def test_non_numeric_shipping_id_is_ignored_not_an_error(self, db) -> None:
        touched = marcar_stale(db, ["MAN_20260101_1"])
        assert touched == 0
