"""RED/GREEN -- `compute_order_metrics` wraps the EXISTING formula functions
and returns identical values to calling them directly, no second formula
(ventas-ml-rediseno PR1.T5, design D7).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentOps
from app.models.varios_venta_pct import VariosVentaPct
from app.services.ml_ventas_desglose.breakdown_service import compute_neto_by_order_ids
from app.services.ml_ventas_desglose.deducciones import calcular_total_gauss
from app.services.ml_ventas_desglose.iva import descomponer_neto
from app.services.order_metrics.compute import compute_order_metrics
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION
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


def _varios(db, porcentaje="0.00") -> None:
    """A baseline "% de varios" version covering everything -- otherwise an
    unconfigured rate blocks the whole chain, unrelated to what these tests
    are actually about (same fixture as test_deducciones.py's own `_varios`)."""
    db.add(VariosVentaPct(porcentaje=Decimal(porcentaje), fecha_desde=date(2020, 1, 1), fecha_hasta=None))


class TestComputeOrderMetricsWrapsExistingFormula:
    def test_ok_order_matches_calling_the_three_functions_directly(self, db) -> None:
        order_id = 5001
        _order(db, order_id)
        # `precio_unitario=100.00` * quantity 2 == the payment's
        # `net_received_amount` below -- must reconcile exactly, or
        # `descomponer_neto` reports `neto_sin_iva=None` (untrustworthy
        # split) and the order can never reach `GaussStatus.OK`.
        _item_with_cost(db, order_id, "MLA1", 2, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("200.00")
            )
        )
        _varios(db)
        db.commit()

        expected_neto = compute_neto_by_order_ids(db, [order_id])
        expected_desc = descomponer_neto(db, [order_id])
        expected_resultado = calcular_total_gauss(
            db,
            [order_id],
            {order_id: expected_desc[order_id].neto_sin_iva},
            venta_sin_iva_by_order={order_id: expected_desc[order_id].base_venta_sin_iva},
        )[order_id]

        metrics = compute_order_metrics(db, [order_id])[order_id]

        assert metrics.neto == expected_neto[order_id]
        assert metrics.neto_sin_iva == expected_desc[order_id].neto_sin_iva
        assert metrics.iva_reconcilia == expected_desc[order_id].reconcilia
        assert metrics.total_gauss == expected_resultado.total_gauss
        assert metrics.markup_pct == expected_resultado.markup
        assert metrics.lineas == expected_resultado.lineas
        assert metrics.formula_version == CURRENT_FORMULA_VERSION
        assert metrics.gauss_status == GaussStatus.OK
        assert metrics.costo_mercaderia == Decimal("20.00")

    def test_provisional_order_status_and_falta(self, db) -> None:
        # `self_service` order with no Flex label loaded yet -- freight
        # unresolved, the DELIBERATE provisional exception (deducciones.py's
        # own docstring), never the generic "block the whole chain" path.
        order_id = 5002
        _order(db, order_id, shipping_id=9502)
        db.add(MlShipmentOps(shipment_id=9502, logistic_type="self_service"))
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        _varios(db)
        db.commit()

        expected_desc = descomponer_neto(db, [order_id])
        expected_resultado = calcular_total_gauss(
            db,
            [order_id],
            {order_id: expected_desc[order_id].neto_sin_iva},
            venta_sin_iva_by_order={order_id: expected_desc[order_id].base_venta_sin_iva},
        )[order_id]

        # The fixture itself must land on the provisional branch -- an
        # assertion nested under `if expected_resultado.provisional:` can
        # pass vacuously if the fixture stops being provisional.
        assert expected_resultado.provisional is True

        metrics = compute_order_metrics(db, [order_id])[order_id]

        assert metrics.gauss_status == GaussStatus.PROVISIONAL
        assert metrics.provisional_falta == expected_resultado.provisional_falta
        assert metrics.total_gauss == expected_resultado.total_gauss

    def test_unresolved_order_has_null_total_gauss_and_a_named_reason(self, db) -> None:
        # No items at all -- `costo_mercaderia` unresolved, which blocks the
        # whole chain (not the Flex-only exception).
        order_id = 5003
        _order(db, order_id)
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()

        metrics = compute_order_metrics(db, [order_id])[order_id]

        assert metrics.gauss_status == GaussStatus.UNRESOLVED
        assert metrics.total_gauss is None
        assert metrics.markup_pct is None
        assert metrics.unresolved_reason is not None

    def test_empty_order_ids_returns_empty_dict(self, db) -> None:
        assert compute_order_metrics(db, []) == {}

    def test_unknown_order_id_is_skipped_not_raised(self, db) -> None:
        # Legacy `persistir_total_gauss` iterated `resultados.items()` and
        # tolerated ids with no `ml_orders_ops` row at all -- an id that
        # simply never made it into the batch is routine, not an error.
        order_id = 5004
        unknown_id = 999999
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()

        result = compute_order_metrics(db, [unknown_id, order_id])

        assert unknown_id not in result
        assert order_id in result

    def test_zero_cost_order_never_raises_markup_pct_is_none(self, db) -> None:
        # `OrderMetrics.__post_init__` rejects a non-None `markup_pct` when
        # `costo_mercaderia` is `None`/zero -- the producer must never
        # disagree with itself and crash the write path over it.
        order_id = 5005
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("0.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()

        metrics = compute_order_metrics(db, [order_id])[order_id]

        assert metrics.costo_mercaderia == Decimal("0.00")
        assert metrics.markup_pct is None

    def test_missing_cost_order_never_raises_markup_pct_is_none(self, db) -> None:
        # No item cost at all -- `costo_mercaderia` unresolved (`None`), and
        # the chain blocks (unresolved status); `markup_pct` must still be
        # `None`, never fabricated, never a crash.
        order_id = 5006
        _order(db, order_id)
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()

        metrics = compute_order_metrics(db, [order_id])[order_id]

        assert metrics.costo_mercaderia is None
        assert metrics.markup_pct is None
