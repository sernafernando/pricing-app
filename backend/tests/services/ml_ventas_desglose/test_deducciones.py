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
    CostoMercaderiaDeduccion,
    DEDUCCIONES,
    EnvioFlexDeduccion,
    VariosDeduccion,
    calcular_total_gauss,
    marcar_stale,
    persistir_total_gauss,
    refrescar_total_gauss_pendientes,
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


class TestAPackSharingOneShipmentPaysTheFreightOnce:
    """A pack can hold several orders under ONE `shipping_id`. Charging
    each of them the whole shipment made the group total -- which sums its
    members -- count the same freight twice, so a two-order Flex pack read
    as costing double what it did.

    The precedent for splitting is already in the sibling module:
    `compute_breakdown` dedupes a pack's billing shipping charge for
    exactly this reason."""

    def _pack_de_dos(self, db, costo: Decimal) -> tuple[int, int]:
        primera, segunda = 8801, 8802
        _order(db, primera, shipping_id=8800)
        _order(db, segunda, shipping_id=8800)
        db.add(MlShipmentOps(shipment_id=8800, logistic_type="self_service"))
        db.add(Logistica(id=88, nombre="Andreani"))
        db.add(EtiquetaEnvio(shipping_id="8800", fecha_envio=date(2026, 8, 1), logistica_id=88, costo_override=costo))
        db.commit()
        return primera, segunda

    def test_the_members_split_it_instead_of_each_paying_it_whole(self, db) -> None:
        primera, segunda = self._pack_de_dos(db, Decimal("300.00"))

        result = EnvioFlexDeduccion().resolve_bulk(db, [primera, segunda])

        assert result[primera] == Decimal("150.00")
        assert result[segunda] == Decimal("150.00")
        # What the group actually paid, which is the number the pack total
        # has to reproduce.
        assert result[primera] + result[segunda] == Decimal("300.00")

    def test_the_split_does_not_depend_on_who_else_is_on_the_page(self, db) -> None:
        """The divisor comes from the DATABASE, not from the batch. Taking
        it from `order_ids` would make one order's freight change depending
        on who else happened to be on the same page -- a number that moves
        when you scroll."""
        primera, _ = self._pack_de_dos(db, Decimal("300.00"))

        solo = EnvioFlexDeduccion().resolve_bulk(db, [primera])

        assert solo[primera] == Decimal("150.00")

    def test_an_order_with_its_own_shipment_still_pays_it_whole(self, db) -> None:
        order_id = 8803
        _order(db, order_id, shipping_id=8810)
        db.add(MlShipmentOps(shipment_id=8810, logistic_type="self_service"))
        db.add(Logistica(id=89, nombre="OCA"))
        db.add(
            EtiquetaEnvio(
                shipping_id="8810", fecha_envio=date(2026, 8, 1), logistica_id=89, costo_override=Decimal("400.00")
            )
        )
        db.commit()

        result = EnvioFlexDeduccion().resolve_bulk(db, [order_id])

        assert result[order_id] == Decimal("400.00")


class TestTheSortKeyHasAProducer:
    """`total_gauss` is a materialised SORT key, so something has to write
    it. Nothing did: every row stayed NULL, `nullslast()` put them all on
    the same side, and "sort by Total Gauss" silently became sort by id.
    The five `marcar_stale` hooks had the mirror problem -- invalidating
    towards a recomputation that did not exist."""

    def test_a_stale_order_gets_rematerialised(self, db) -> None:
        order_id = 9501
        _order(db, order_id)
        db.query(MlOrdersOps).filter_by(order_id=order_id).update(
            {"total_gauss": Decimal("1.00"), "total_gauss_at": datetime.now(timezone.utc), "total_gauss_stale": True}
        )
        db.commit()

        refrescados = refrescar_total_gauss_pendientes(db)
        db.commit()

        assert refrescados == 1
        row = db.query(MlOrdersOps).filter_by(order_id=order_id).one()
        assert row.total_gauss_stale is False, "the flag stays raised forever if nothing lowers it"

    def test_an_order_never_materialised_is_picked_up(self, db) -> None:
        order_id = 9502
        _order(db, order_id)
        db.commit()

        refrescados = refrescar_total_gauss_pendientes(db)
        db.commit()

        assert refrescados == 1
        assert db.query(MlOrdersOps).filter_by(order_id=order_id).one().total_gauss_at is not None

    def test_an_already_fresh_order_is_left_alone(self, db) -> None:
        """Otherwise every pass would redo the whole table."""
        order_id = 9503
        _order(db, order_id)
        db.commit()
        refrescar_total_gauss_pendientes(db)
        db.commit()

        assert refrescar_total_gauss_pendientes(db) == 0

    def test_the_pass_is_bounded(self, db) -> None:
        """A large backlog must not turn the sweep into this job."""
        for offset in range(5):
            _order(db, 9600 + offset)
        db.commit()

        assert refrescar_total_gauss_pendientes(db, limit=2) == 2


class TestADeductionThatStoppedApplyingLosesItsRow:
    """`total_gauss` stays right either way -- it is recomputed whole. It
    is the persisted breakdown that would keep lying, against its own model
    docstring ("the last-resolved amount of one deduction")."""

    def test_the_flex_row_disappears_when_the_order_stops_being_flex(self, db) -> None:
        order_id = 9701
        _order(db, order_id, shipping_id=9700)
        db.add(MlShipmentOps(shipment_id=9700, logistic_type="self_service"))
        db.add(Logistica(id=97, nombre="Andreani"))
        db.add(
            EtiquetaEnvio(
                shipping_id="9700", fecha_envio=date(2026, 8, 1), logistica_id=97, costo_override=Decimal("500.00")
            )
        )
        db.commit()

        persistir_total_gauss(db, [order_id])
        db.commit()
        assert db.query(MlVentaDeduccion).filter_by(order_id=order_id, code="envio_flex").count() == 1

        # The shipment turns out not to be Flex after all.
        db.query(MlShipmentOps).filter_by(shipment_id=9700).update({"logistic_type": "cross_docking"})
        db.commit()

        persistir_total_gauss(db, [order_id])
        db.commit()

        assert db.query(MlVentaDeduccion).filter_by(order_id=order_id, code="envio_flex").count() == 0
