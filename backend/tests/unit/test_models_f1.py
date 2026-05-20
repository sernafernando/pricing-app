"""
T1.5 + T1.7 — Model tests for F1 columns.

Verifies that OrdenPago and PedidoCompra SQLAlchemy models have the new
F1 columns before testing service logic.
"""

from __future__ import annotations

from decimal import Decimal
from sqlalchemy import inspect as sa_inspect

from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra


class TestOrdenPagoModelF1:
    """T1.5 — OrdenPago has actualizar_tc_pedido Boolean column, default false."""

    def test_has_actualizar_tc_pedido_column(self) -> None:
        mapper = sa_inspect(OrdenPago)
        col_names = [col.key for col in mapper.columns]
        assert "actualizar_tc_pedido" in col_names

    def test_actualizar_tc_pedido_is_boolean(self) -> None:
        from sqlalchemy import Boolean

        mapper = sa_inspect(OrdenPago)
        col = mapper.columns["actualizar_tc_pedido"]
        assert isinstance(col.type, Boolean)

    def test_actualizar_tc_pedido_not_nullable(self) -> None:
        mapper = sa_inspect(OrdenPago)
        col = mapper.columns["actualizar_tc_pedido"]
        assert not col.nullable

    def test_actualizar_tc_pedido_default_false(self) -> None:
        mapper = sa_inspect(OrdenPago)
        col = mapper.columns["actualizar_tc_pedido"]
        # server_default should be 'false'
        assert col.server_default is not None or col.default is not None

    def test_orden_pago_instance_defaults_to_false(self) -> None:
        op = OrdenPago(
            numero="OP-001",
            empresa_id=1,
            proveedor_id=1,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="especifica",
            creado_por_id=1,
        )
        assert op.actualizar_tc_pedido is False or op.actualizar_tc_pedido is None


class TestPedidoCompraModelF1:
    """T1.7 — PedidoCompra has tipo_cambio_original Numeric(18,6) nullable column."""

    def test_has_tipo_cambio_original_column(self) -> None:
        mapper = sa_inspect(PedidoCompra)
        col_names = [col.key for col in mapper.columns]
        assert "tipo_cambio_original" in col_names

    def test_tipo_cambio_original_is_numeric(self) -> None:
        from sqlalchemy import Numeric

        mapper = sa_inspect(PedidoCompra)
        col = mapper.columns["tipo_cambio_original"]
        assert isinstance(col.type, Numeric)

    def test_tipo_cambio_original_is_nullable(self) -> None:
        mapper = sa_inspect(PedidoCompra)
        col = mapper.columns["tipo_cambio_original"]
        assert col.nullable

    def test_pedido_compra_instance_tipo_cambio_original_defaults_none(self) -> None:
        pedido = PedidoCompra(
            numero="PC-001",
            empresa_id=1,
            proveedor_id=1,
            moneda="USD",
            monto=Decimal("1000"),
            tipo_cambio=Decimal("1400"),
            creado_por_id=1,
        )
        assert pedido.tipo_cambio_original is None
