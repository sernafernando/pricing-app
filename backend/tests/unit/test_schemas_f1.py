"""
T1.9 — Schema tests for F1: OrdenPagoCreate, OrdenPagoResponse, PedidoCompraResponse.
"""

from __future__ import annotations

from decimal import Decimal


from app.schemas.orden_pago import OrdenPagoCreate, OrdenPagoResponse
from app.schemas.pedido_compra import PedidoCompraResponse


class TestOrdenPagoSchemaF1:
    """OrdenPagoCreate and OrdenPagoResponse include actualizar_tc_pedido."""

    def test_create_accepts_actualizar_tc_pedido_false(self) -> None:
        payload = OrdenPagoCreate(
            empresa_id=1,
            proveedor_id=1,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="especifica",
            actualizar_tc_pedido=False,
        )
        assert payload.actualizar_tc_pedido is False

    def test_create_accepts_actualizar_tc_pedido_true(self) -> None:
        payload = OrdenPagoCreate(
            empresa_id=1,
            proveedor_id=1,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="especifica",
            actualizar_tc_pedido=True,
        )
        assert payload.actualizar_tc_pedido is True

    def test_create_defaults_actualizar_tc_pedido_to_false(self) -> None:
        payload = OrdenPagoCreate(
            empresa_id=1,
            proveedor_id=1,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="especifica",
        )
        assert payload.actualizar_tc_pedido is False

    def test_response_includes_actualizar_tc_pedido(self) -> None:
        """OrdenPagoResponse (from_attributes) can serialize actualizar_tc_pedido."""
        from datetime import datetime

        data = {
            "id": 1,
            "numero": "OP-001",
            "empresa_id": 1,
            "proveedor_id": 1,
            "moneda": "ARS",
            "monto_total": Decimal("1000"),
            "modo_imputacion": "especifica",
            "estado": "pendiente",
            "actualizar_tc_pedido": True,
            "creado_por_id": 1,
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
        }
        resp = OrdenPagoResponse(**data)
        assert resp.actualizar_tc_pedido is True


class TestPedidoCompraSchemaF1:
    """PedidoCompraResponse includes tipo_cambio_original."""

    def test_response_includes_tipo_cambio_original(self) -> None:
        from datetime import datetime

        data = {
            "id": 1,
            "numero": "PC-001",
            "empresa_id": 1,
            "proveedor_id": 1,
            "moneda": "USD",
            "monto": Decimal("1000"),
            "tipo_cambio": Decimal("1450"),
            "tipo_cambio_original": Decimal("1400"),
            "estado": "aprobado",
            "creado_por_id": 1,
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
        }
        resp = PedidoCompraResponse(**data)
        assert resp.tipo_cambio_original == Decimal("1400")

    def test_response_tipo_cambio_original_defaults_to_none(self) -> None:
        from datetime import datetime

        data = {
            "id": 1,
            "numero": "PC-001",
            "empresa_id": 1,
            "proveedor_id": 1,
            "moneda": "ARS",
            "monto": Decimal("5000"),
            "estado": "borrador",
            "creado_por_id": 1,
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
        }
        resp = PedidoCompraResponse(**data)
        assert resp.tipo_cambio_original is None
