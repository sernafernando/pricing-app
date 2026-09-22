"""RED/GREEN -- `compute_order_metrics` wraps the EXISTING formula functions
and returns identical values to calling them directly, no second formula
(ventas-ml-rediseno PR1.T5, design D7).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_ventas_desglose.breakdown_service import compute_neto_by_order_ids
from app.services.ml_ventas_desglose.deducciones import calcular_total_gauss
from app.services.ml_ventas_desglose.iva import descomponer_neto
from app.services.order_metrics.compute import compute_order_metrics
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION
from app.services.order_metrics.types import GaussStatus


def _order(db, order_id: int) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            date_created=datetime(2026, 8, 15, tzinfo=timezone.utc),
            seller_id=999,
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


class TestComputeOrderMetricsWrapsExistingFormula:
    def test_ok_order_matches_calling_the_three_functions_directly(self, db) -> None:
        order_id = 5001
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 2, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
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

    def test_provisional_order_status_and_falta(self, db) -> None:
        # No shipping label at all yet -- Flex freight unresolved, the
        # DELIBERATE provisional exception (deducciones.py's own docstring).
        order_id = 5002
        _order(db, order_id)
        _item_with_cost(db, order_id, "MLA1", 1, Decimal("10.00"))
        db.add(
            MlPaymentOps(
                payment_id=order_id, order_id=order_id, status="approved", net_received_amount=Decimal("100.00")
            )
        )
        db.commit()

        expected_desc = descomponer_neto(db, [order_id])
        expected_resultado = calcular_total_gauss(
            db,
            [order_id],
            {order_id: expected_desc[order_id].neto_sin_iva},
            venta_sin_iva_by_order={order_id: expected_desc[order_id].base_venta_sin_iva},
        )[order_id]

        metrics = compute_order_metrics(db, [order_id])[order_id]

        if expected_resultado.provisional:
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
