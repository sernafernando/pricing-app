"""
T3.1 — Unit tests for F7 PR#2b schemas: OrdenPagoEjecutarPago con banco_id.

Cubre:
  - caja_id set, banco_id None → válido.
  - caja_id None, banco_id set → válido.
  - ambos set → 422 (exactamente una fuente).
  - ambos None → 422 (se requiere al menos una fuente al pagar).
  - OrdenPagoResponse tiene banco_id y banco_movimiento_id.
  - OrdenPagoCrearYPagar acepta banco_id (hereda del validator).
  - OrdenPagoDetalle expone banco_nombre (follow-up #3).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.orden_pago import (
    OrdenPagoCrearYPagar,
    OrdenPagoDetalle,
    OrdenPagoEjecutarPago,
    OrdenPagoResponse,
)


class TestOrdenPagoEjecutarPago:
    """Schema validator: exactamente una fuente de fondos al pagar."""

    def test_caja_id_only_valid(self) -> None:
        """caja_id set, banco_id=None → válido."""
        schema = OrdenPagoEjecutarPago(caja_id=3, banco_id=None, fecha_pago_real="2026-05-21")
        assert schema.caja_id == 3
        assert schema.banco_id is None

    def test_banco_id_only_valid(self) -> None:
        """banco_id set, caja_id=None → válido."""
        schema = OrdenPagoEjecutarPago(caja_id=None, banco_id=5, fecha_pago_real="2026-05-21")
        assert schema.banco_id == 5
        assert schema.caja_id is None

    def test_both_set_invalid(self) -> None:
        """Ambos caja_id y banco_id provistos → ValidationError (AC-F2-7)."""
        with pytest.raises(ValidationError) as exc_info:
            OrdenPagoEjecutarPago(caja_id=3, banco_id=5, fecha_pago_real="2026-05-21")
        errors = exc_info.value.errors()
        assert any("fuente" in str(e).lower() or "solo" in str(e).lower() for e in errors)

    def test_both_none_invalid(self) -> None:
        """Ambos None → ValidationError (se requiere exactamente una fuente)."""
        with pytest.raises(ValidationError) as exc_info:
            OrdenPagoEjecutarPago(caja_id=None, banco_id=None, fecha_pago_real="2026-05-21")
        errors = exc_info.value.errors()
        assert len(errors) >= 1

    def test_default_no_banco(self) -> None:
        """El campo banco_id por defecto es None; caja_id sigue funcionando sin cambiarlo."""
        # Backward-compat: el viejo schema solo tenía caja_id (int, requerido).
        # Ahora caja_id es Optional y banco_id es Optional, pero el validator
        # exige exactamente uno.
        schema = OrdenPagoEjecutarPago(caja_id=7, fecha_pago_real="2026-05-21")
        assert schema.caja_id == 7
        assert schema.banco_id is None


class TestOrdenPagoResponse:
    """OrdenPagoResponse expone banco_id y banco_movimiento_id."""

    def _base(self) -> dict:
        return {
            "id": 1,
            "numero": "OP-001",
            "empresa_id": 1,
            "proveedor_id": 2,
            "moneda": "ARS",
            "monto_total": Decimal("10000"),
            "modo_imputacion": "a_cuenta",
            "estado": "pendiente",
            "creado_por_id": 1,
            "created_at": "2026-05-21T00:00:00Z",
            "updated_at": "2026-05-21T00:00:00Z",
        }

    def test_banco_fields_default_none(self) -> None:
        """banco_id y banco_movimiento_id son None por defecto."""
        resp = OrdenPagoResponse(**self._base())
        assert resp.banco_id is None
        assert resp.banco_movimiento_id is None

    def test_banco_fields_populated(self) -> None:
        """banco_id y banco_movimiento_id pueden ser seteados."""
        data = self._base()
        data["banco_id"] = 5
        data["banco_movimiento_id"] = 99
        resp = OrdenPagoResponse(**data)
        assert resp.banco_id == 5
        assert resp.banco_movimiento_id == 99


class TestOrdenPagoCrearYPagarBanco:
    """OrdenPagoCrearYPagar hereda el validator de OrdenPagoEjecutarPago."""

    def _base(self) -> dict:
        return {
            "empresa_id": 1,
            "proveedor_id": 2,
            "moneda": "ARS",
            "monto_total": Decimal("10000"),
            "modo_imputacion": "a_cuenta",
            "fecha_pago_real": "2026-05-21",
        }

    def test_with_banco_id_valid(self) -> None:
        """banco_id set, caja_id=None → válido."""
        schema = OrdenPagoCrearYPagar(**self._base(), banco_id=5)
        assert schema.banco_id == 5
        assert schema.caja_id is None

    def test_with_caja_id_valid(self) -> None:
        """caja_id set, banco_id=None → válido (backward-compat)."""
        schema = OrdenPagoCrearYPagar(**self._base(), caja_id=3)
        assert schema.caja_id == 3
        assert schema.banco_id is None

    def test_both_invalid(self) -> None:
        """Ambos set → ValidationError."""
        with pytest.raises(ValidationError):
            OrdenPagoCrearYPagar(**self._base(), caja_id=3, banco_id=5)


class TestOrdenPagoDetalleBancoNombre:
    """OrdenPagoDetalle expone banco_nombre (follow-up #3).

    Verifica que el campo banco_nombre esté presente en el schema y que:
    - Sea None por defecto (OP de caja o pendiente).
    - Acepte el nombre del banco cuando la OP fue pagada con banco.
    """

    def _base(self) -> dict:
        return {
            "id": 1,
            "numero": "OP-001",
            "empresa_id": 1,
            "proveedor_id": 2,
            "moneda": "ARS",
            "monto_total": Decimal("10000"),
            "modo_imputacion": "a_cuenta",
            "estado": "pendiente",
            "creado_por_id": 1,
            "created_at": "2026-05-21T00:00:00Z",
            "updated_at": "2026-05-21T00:00:00Z",
        }

    def test_banco_nombre_defaults_none(self) -> None:
        """banco_nombre es None cuando no se provee (OP de caja o pendiente)."""
        detalle = OrdenPagoDetalle(**self._base())
        assert detalle.banco_nombre is None

    def test_banco_nombre_populated(self) -> None:
        """banco_nombre acepta el nombre del banco cuando la OP fue pagada con banco."""
        detalle = OrdenPagoDetalle(**self._base(), banco_id=5, banco_nombre="Banco Galicia")
        assert detalle.banco_nombre == "Banco Galicia"
        assert detalle.banco_id == 5

    def test_banco_nombre_none_when_caja_payment(self) -> None:
        """Pago por caja: banco_nombre es None, caja_movimiento_resumen llevará el detalle."""
        detalle = OrdenPagoDetalle(**self._base(), caja_id=3, banco_nombre=None)
        assert detalle.banco_nombre is None
        assert detalle.caja_movimiento_resumen is None
