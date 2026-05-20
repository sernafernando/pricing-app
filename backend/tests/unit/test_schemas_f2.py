"""
T2.5 — Schema tests for F2:
  - NotaCreditoLocalCreate accepts tipo: Literal['credito','debito'] = 'credito'.
  - NotaCreditoLocalResponse includes tipo.
  - PedidoCompraResponse includes varianza_tc_pendiente: bool and varianza_tc_neta: Decimal.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from pydantic import ValidationError

from app.schemas.nota_credito_local import NotaCreditoLocalCreate, NotaCreditoLocalResponse
from app.schemas.pedido_compra import PedidoCompraResponse


class TestNotaCreditoLocalSchemaF2:
    """NotaCreditoLocalCreate and NotaCreditoLocalResponse include tipo."""

    def test_create_defaults_to_credito(self) -> None:
        payload = NotaCreditoLocalCreate(
            empresa_id=1,
            proveedor_id=1,
            moneda="ARS",
            monto=Decimal("1000"),
            fecha_emision=date(2026, 1, 1),
            motivo="test",
        )
        assert payload.tipo == "credito"

    def test_create_accepts_credito(self) -> None:
        payload = NotaCreditoLocalCreate(
            empresa_id=1,
            proveedor_id=1,
            moneda="ARS",
            monto=Decimal("1000"),
            fecha_emision=date(2026, 1, 1),
            motivo="test",
            tipo="credito",
        )
        assert payload.tipo == "credito"

    def test_create_accepts_debito(self) -> None:
        payload = NotaCreditoLocalCreate(
            empresa_id=1,
            proveedor_id=1,
            moneda="ARS",
            monto=Decimal("1000"),
            fecha_emision=date(2026, 1, 1),
            motivo="test",
            tipo="debito",
        )
        assert payload.tipo == "debito"

    def test_create_rejects_invalid_tipo(self) -> None:
        with pytest.raises(ValidationError):
            NotaCreditoLocalCreate(
                empresa_id=1,
                proveedor_id=1,
                moneda="ARS",
                monto=Decimal("1000"),
                fecha_emision=date(2026, 1, 1),
                motivo="test",
                tipo="invalido",
            )

    def test_response_includes_tipo(self) -> None:
        now = datetime.now()
        resp = NotaCreditoLocalResponse(
            id=1,
            numero="NC-001",
            empresa_id=1,
            proveedor_id=1,
            moneda="ARS",
            monto=Decimal("1000"),
            fecha_emision=date(2026, 1, 1),
            motivo="test",
            estado="aprobado",
            creado_por_id=1,
            created_at=now,
            updated_at=now,
            tipo="credito",
        )
        assert resp.tipo == "credito"

    def test_response_tipo_defaults_to_credito(self) -> None:
        now = datetime.now()
        resp = NotaCreditoLocalResponse(
            id=1,
            numero="NC-001",
            empresa_id=1,
            proveedor_id=1,
            moneda="ARS",
            monto=Decimal("1000"),
            fecha_emision=date(2026, 1, 1),
            motivo="test",
            estado="aprobado",
            creado_por_id=1,
            created_at=now,
            updated_at=now,
        )
        assert resp.tipo == "credito"


class TestPedidoCompraResponseF2:
    """PedidoCompraResponse includes varianza_tc_pendiente and varianza_tc_neta."""

    def _make_response(self, **kwargs: object) -> PedidoCompraResponse:
        now = datetime.now()
        defaults: dict = dict(
            id=1,
            numero="PC-001",
            empresa_id=1,
            proveedor_id=1,
            moneda="USD",
            monto=Decimal("1000"),
            tipo_cambio=Decimal("1400"),
            fecha_pago_texto=None,
            fecha_pago_estimada=None,
            requiere_envio=False,
            numero_factura=None,
            observaciones=None,
            ct_transaction_id=None,
            estado="aprobado",
            creado_por_id=1,
            aprobado_por_id=None,
            created_at=now,
            updated_at=now,
        )
        defaults.update(kwargs)
        return PedidoCompraResponse(**defaults)

    def test_varianza_tc_pendiente_defaults_false(self) -> None:
        resp = self._make_response()
        assert resp.varianza_tc_pendiente is False

    def test_varianza_tc_neta_defaults_zero(self) -> None:
        resp = self._make_response()
        assert resp.varianza_tc_neta == Decimal("0")

    def test_varianza_tc_pendiente_can_be_true(self) -> None:
        resp = self._make_response(varianza_tc_pendiente=True, varianza_tc_neta=Decimal("50000"))
        assert resp.varianza_tc_pendiente is True
        assert resp.varianza_tc_neta == Decimal("50000")
