"""flex-envio-comprador: the panel's "Envío cobrado al comprador" line for the
Flex shipping no payment carries gets its gross / net / IVA from the SAME
`iva.py` component the IVA section shows, like the bonificación line."""

from __future__ import annotations

import pytest

from app.routers.ml_ventas_ops import OperationBreakdownSummary, _con_importe_de_bonificacion
from app.services.ml_ventas_desglose.breakdown_service import CONCEPTO_ENVIO_COMPRADOR, compute_breakdown
from app.services.ml_ventas_desglose.iva import descomponer_neto
from tests.services.ml_ventas_desglose._flex_receiver_capture import ORDER_5990, seed_order_5990


def _summary(db):
    breakdown = compute_breakdown(db, [ORDER_5990])
    desc = descomponer_neto(db, [ORDER_5990])[ORDER_5990]
    return _con_importe_de_bonificacion(OperationBreakdownSummary.from_domain(breakdown), desc)


def test_the_flex_buyer_shipping_line_carries_its_importe(db) -> None:
    seed_order_5990(db)

    line = next(line for line in _summary(db).lines if line.concepto == CONCEPTO_ENVIO_COMPRADOR)

    assert line.origen == "envio_comprador"
    assert line.monto == pytest.approx(-5990)
    assert (line.importe.bruto, line.importe.neto, line.importe.iva) == pytest.approx((5990, 4950.41, 1039.59))


def test_a_payment_carried_shipping_adds_no_line(db) -> None:
    """Inside the payment there is no breakdown line (and so no importe)."""
    seed_order_5990(db, shipping_amount=5990.0, net_received_amount=15034.0)

    assert CONCEPTO_ENVIO_COMPRADOR not in [line.concepto for line in _summary(db).lines]
