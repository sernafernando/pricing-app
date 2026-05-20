"""
T3.1 — Schema tests for F3: OrdenPagoCrearYPagar.

Verifies:
  - OrdenPagoCrearYPagar includes all OrdenPagoCreate fields.
  - Required fields: caja_id (int), fecha_pago_real (date).
  - Optional fields: tipo_cambio_override.
  - actualizar_tc_pedido defaults to False.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.orden_pago import OrdenPagoCrearYPagar


PAYLOAD_BASE = {
    "empresa_id": 1,
    "proveedor_id": 1,
    "moneda": "ARS",
    "monto_total": Decimal("50000"),
    "modo_imputacion": "especifica",
    "caja_id": 3,
    "fecha_pago_real": date(2026, 1, 15),
}


class TestOrdenPagoCrearYPagar:
    """T3.1 — OrdenPagoCrearYPagar schema validation."""

    def test_happy_path_minimal(self) -> None:
        """All OrdenPagoCreate fields + caja_id + fecha_pago_real."""
        payload = OrdenPagoCrearYPagar(**PAYLOAD_BASE)
        assert payload.empresa_id == 1
        assert payload.proveedor_id == 1
        assert payload.moneda == "ARS"
        assert payload.monto_total == Decimal("50000")
        assert payload.modo_imputacion == "especifica"
        assert payload.caja_id == 3
        assert payload.fecha_pago_real == date(2026, 1, 15)

    def test_caja_id_required(self) -> None:
        """Missing caja_id → ValidationError."""
        payload = {k: v for k, v in PAYLOAD_BASE.items() if k != "caja_id"}
        with pytest.raises(ValidationError):
            OrdenPagoCrearYPagar(**payload)

    def test_fecha_pago_real_required(self) -> None:
        """Missing fecha_pago_real → ValidationError."""
        payload = {k: v for k, v in PAYLOAD_BASE.items() if k != "fecha_pago_real"}
        with pytest.raises(ValidationError):
            OrdenPagoCrearYPagar(**payload)

    def test_tipo_cambio_override_optional_defaults_none(self) -> None:
        """tipo_cambio_override is optional, defaults None."""
        payload = OrdenPagoCrearYPagar(**PAYLOAD_BASE)
        assert payload.tipo_cambio_override is None

    def test_tipo_cambio_override_accepted(self) -> None:
        """tipo_cambio_override can be set."""
        payload = OrdenPagoCrearYPagar(**PAYLOAD_BASE, tipo_cambio_override=Decimal("1450"))
        assert payload.tipo_cambio_override == Decimal("1450")

    def test_actualizar_tc_pedido_defaults_false(self) -> None:
        """actualizar_tc_pedido inherits from OrdenPagoCreate with default False."""
        payload = OrdenPagoCrearYPagar(**PAYLOAD_BASE)
        assert payload.actualizar_tc_pedido is False

    def test_actualizar_tc_pedido_accepted(self) -> None:
        """actualizar_tc_pedido can be set to True (F1 Caso A)."""
        payload = OrdenPagoCrearYPagar(**PAYLOAD_BASE, actualizar_tc_pedido=True)
        assert payload.actualizar_tc_pedido is True

    def test_items_defaults_empty(self) -> None:
        """items defaults to empty list (inherited from OrdenPagoCreate)."""
        payload = OrdenPagoCrearYPagar(**PAYLOAD_BASE)
        assert payload.items == []

    def test_items_accepted(self) -> None:
        """items can be passed and are stored."""
        items = [{"tipo": "pedido_compra", "id": 5, "monto": Decimal("50000")}]
        payload = OrdenPagoCrearYPagar(**PAYLOAD_BASE, items=items)
        assert len(payload.items) == 1
        assert payload.items[0].tipo == "pedido_compra"

    def test_moneda_validation(self) -> None:
        """moneda must be ARS or USD."""
        with pytest.raises(ValidationError):
            OrdenPagoCrearYPagar(**{**PAYLOAD_BASE, "moneda": "EUR"})

    def test_confirmar_duplicado_defaults_false(self) -> None:
        """confirmar_duplicado inherits from OrdenPagoCreate."""
        payload = OrdenPagoCrearYPagar(**PAYLOAD_BASE)
        assert payload.confirmar_duplicado is False
