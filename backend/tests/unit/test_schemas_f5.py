"""
T5.5 — Schema tests for F5: PedidoTipoCambioUpdate and PedidoCompraResponse F5 fields.

Verifies:
  - PedidoTipoCambioUpdate: tipo_cambio Optional[Decimal], motivo str (required).
  - PedidoCompraResponse gains tipo_cambio_manual (Optional[Decimal]).
  - PedidoCompraResponse gains tipo_cambio_es_manual (bool, computed from tipo_cambio_manual).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.pedido_compra import PedidoCompraResponse, PedidoTipoCambioUpdate


class TestPedidoTipoCambioUpdate:
    """T5.5a — PedidoTipoCambioUpdate schema."""

    def test_happy_path_set_override(self) -> None:
        """tipo_cambio Decimal + motivo → valid."""
        req = PedidoTipoCambioUpdate(tipo_cambio=Decimal("1430"), motivo="ajuste manual")
        assert req.tipo_cambio == Decimal("1430")
        assert req.motivo == "ajuste manual"

    def test_happy_path_clear_override(self) -> None:
        """tipo_cambio null → valid (clears override)."""
        req = PedidoTipoCambioUpdate(tipo_cambio=None, motivo="volvemos a automático")
        assert req.tipo_cambio is None

    def test_motivo_required(self) -> None:
        """Missing motivo → ValidationError."""
        with pytest.raises(ValidationError):
            PedidoTipoCambioUpdate(tipo_cambio=Decimal("1430"))

    def test_tipo_cambio_must_be_positive(self) -> None:
        """tipo_cambio <= 0 → ValidationError."""
        with pytest.raises(ValidationError):
            PedidoTipoCambioUpdate(tipo_cambio=Decimal("0"), motivo="test")

    def test_tipo_cambio_optional_defaults_none(self) -> None:
        """tipo_cambio optional — can be omitted (defaults None)."""
        req = PedidoTipoCambioUpdate(motivo="test")
        assert req.tipo_cambio is None


class TestPedidoCompraResponseF5Fields:
    """T5.5b — PedidoCompraResponse has tipo_cambio_manual + tipo_cambio_es_manual."""

    def _make_response_kwargs(self, **overrides: object) -> dict:
        """Minimal valid kwargs for PedidoCompraResponse."""
        base = {
            "id": 1,
            "numero": "PC-001",
            "empresa_id": 1,
            "proveedor_id": 1,
            "moneda": "USD",
            "monto": Decimal("1000"),
            "tipo_cambio": Decimal("1400"),
            "estado": "aprobado",
            "creado_por_id": 1,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        base.update(overrides)
        return base

    def test_tipo_cambio_manual_defaults_none(self) -> None:
        resp = PedidoCompraResponse(**self._make_response_kwargs())
        assert resp.tipo_cambio_manual is None

    def test_tipo_cambio_es_manual_false_when_no_override(self) -> None:
        resp = PedidoCompraResponse(**self._make_response_kwargs())
        assert resp.tipo_cambio_es_manual is False

    def test_tipo_cambio_manual_populated(self) -> None:
        resp = PedidoCompraResponse(**self._make_response_kwargs(tipo_cambio_manual=Decimal("1430")))
        assert resp.tipo_cambio_manual == Decimal("1430")

    def test_tipo_cambio_es_manual_true_when_override_set(self) -> None:
        resp = PedidoCompraResponse(**self._make_response_kwargs(tipo_cambio_manual=Decimal("1430")))
        assert resp.tipo_cambio_es_manual is True
