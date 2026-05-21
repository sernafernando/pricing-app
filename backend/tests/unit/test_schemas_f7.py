"""
T1.1 — Tests unitarios para los schemas F7: NCAplicadaItem y OrdenPagoCreate/CrearYPagar.

Cubre:
  - NCAplicadaItem valid: nc_id, monto > 0, pedido_id optional.
  - NCAplicadaItem invalid: monto = 0, monto < 0, nc_id < 1.
  - OrdenPagoCreate acepta ncs_aplicadas: [] (default) y lista poblada.
  - OrdenPagoCrearYPagar hereda ncs_aplicadas (sin override manual).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.orden_pago import NCAplicadaItem, OrdenPagoCreate, OrdenPagoCrearYPagar


class TestNCAplicadaItem:
    """Tests para el schema NCAplicadaItem."""

    def test_valid_minimal(self) -> None:
        """nc_id y monto son los únicos campos requeridos; pedido_id es opcional."""
        item = NCAplicadaItem(nc_id=1, monto=Decimal("5000"))
        assert item.nc_id == 1
        assert item.monto == Decimal("5000")
        assert item.pedido_id is None

    def test_valid_with_pedido_id(self) -> None:
        """Todos los campos válidos."""
        item = NCAplicadaItem(nc_id=10, monto=Decimal("1000.50"), pedido_id=20)
        assert item.nc_id == 10
        assert item.pedido_id == 20

    def test_monto_zero_invalid(self) -> None:
        """monto = 0 debe fallar (gt=0)."""
        with pytest.raises(ValidationError) as exc_info:
            NCAplicadaItem(nc_id=1, monto=Decimal("0"))
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("monto",) for e in errors)

    def test_monto_negative_invalid(self) -> None:
        """monto < 0 debe fallar (gt=0)."""
        with pytest.raises(ValidationError) as exc_info:
            NCAplicadaItem(nc_id=1, monto=Decimal("-100"))
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("monto",) for e in errors)

    def test_nc_id_zero_invalid(self) -> None:
        """nc_id = 0 debe fallar (ge=1)."""
        with pytest.raises(ValidationError) as exc_info:
            NCAplicadaItem(nc_id=0, monto=Decimal("100"))
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("nc_id",) for e in errors)

    def test_nc_id_negative_invalid(self) -> None:
        """nc_id < 0 debe fallar (ge=1)."""
        with pytest.raises(ValidationError) as exc_info:
            NCAplicadaItem(nc_id=-5, monto=Decimal("100"))
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("nc_id",) for e in errors)


class TestOrdenPagoCreateNCs:
    """Tests para ncs_aplicadas en OrdenPagoCreate."""

    def _base_payload(self) -> dict:
        return {
            "empresa_id": 1,
            "proveedor_id": 2,
            "moneda": "ARS",
            "monto_total": Decimal("10000"),
            "modo_imputacion": "a_cuenta",
        }

    def test_ncs_aplicadas_defaults_to_empty_list(self) -> None:
        """Ausencia de ncs_aplicadas → lista vacía (comportamiento existente sin cambio)."""
        op = OrdenPagoCreate(**self._base_payload())
        assert op.ncs_aplicadas == []

    def test_ncs_aplicadas_empty_list_explicit(self) -> None:
        """ncs_aplicadas: [] explícito → lista vacía."""
        op = OrdenPagoCreate(**self._base_payload(), ncs_aplicadas=[])
        assert op.ncs_aplicadas == []

    def test_ncs_aplicadas_populated(self) -> None:
        """ncs_aplicadas con ítems válidos."""
        payload = self._base_payload()
        payload["ncs_aplicadas"] = [
            {"nc_id": 10, "monto": "5000", "pedido_id": 20},
            {"nc_id": 11, "monto": "3000"},
        ]
        op = OrdenPagoCreate(**payload)
        assert len(op.ncs_aplicadas) == 2
        assert op.ncs_aplicadas[0].nc_id == 10
        assert op.ncs_aplicadas[0].pedido_id == 20
        assert op.ncs_aplicadas[1].pedido_id is None


class TestOrdenPagoCrearYPagarNCs:
    """OrdenPagoCrearYPagar hereda ncs_aplicadas de OrdenPagoCreate."""

    def _base_payload(self) -> dict:
        return {
            "empresa_id": 1,
            "proveedor_id": 2,
            "moneda": "ARS",
            "monto_total": Decimal("10000"),
            "modo_imputacion": "a_cuenta",
            "caja_id": 3,
            "fecha_pago_real": "2026-05-21",
        }

    def test_hereda_ncs_aplicadas_vacio(self) -> None:
        """Sin ncs_aplicadas → lista vacía (herencia correcta, sin override)."""
        schema = OrdenPagoCrearYPagar(**self._base_payload())
        assert schema.ncs_aplicadas == []

    def test_hereda_ncs_aplicadas_poblado(self) -> None:
        """ncs_aplicadas heredado con ítems."""
        payload = self._base_payload()
        payload["ncs_aplicadas"] = [{"nc_id": 5, "monto": "1000"}]
        schema = OrdenPagoCrearYPagar(**payload)
        assert len(schema.ncs_aplicadas) == 1
        assert schema.ncs_aplicadas[0].nc_id == 5
