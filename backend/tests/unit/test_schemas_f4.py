"""
T4.1 — Schema tests for F4: AplicarNCDesdeOPRequest.

Verifies:
  - nc_id (int, required).
  - monto (Decimal, required, > 0).
  - pedido_id (Optional[int], default None).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.orden_pago import AplicarNCDesdeOPRequest


class TestAplicarNCDesdeOPRequest:
    """T4.1 — AplicarNCDesdeOPRequest schema validation."""

    def test_happy_path_minimal(self) -> None:
        """nc_id + monto only — pedido_id optional."""
        req = AplicarNCDesdeOPRequest(nc_id=3, monto=Decimal("5000"))
        assert req.nc_id == 3
        assert req.monto == Decimal("5000")
        assert req.pedido_id is None

    def test_happy_path_with_pedido_id(self) -> None:
        """All three fields provided."""
        req = AplicarNCDesdeOPRequest(nc_id=3, monto=Decimal("5000"), pedido_id=7)
        assert req.pedido_id == 7

    def test_nc_id_required(self) -> None:
        """Missing nc_id → ValidationError."""
        with pytest.raises(ValidationError):
            AplicarNCDesdeOPRequest(monto=Decimal("5000"))

    def test_monto_required(self) -> None:
        """Missing monto → ValidationError."""
        with pytest.raises(ValidationError):
            AplicarNCDesdeOPRequest(nc_id=3)

    def test_monto_must_be_positive(self) -> None:
        """monto <= 0 → ValidationError."""
        with pytest.raises(ValidationError):
            AplicarNCDesdeOPRequest(nc_id=3, monto=Decimal("0"))
        with pytest.raises(ValidationError):
            AplicarNCDesdeOPRequest(nc_id=3, monto=Decimal("-100"))

    def test_pedido_id_defaults_none(self) -> None:
        """pedido_id absent → defaults to None."""
        req = AplicarNCDesdeOPRequest(nc_id=1, monto=Decimal("100"))
        assert req.pedido_id is None
