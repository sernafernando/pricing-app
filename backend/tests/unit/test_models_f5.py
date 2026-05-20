"""
T5.3 — Model test for F5: PedidoCompra has tipo_cambio_manual column.

Verifies the SQLAlchemy model exposes the new column before any service
logic is tested.
"""

from __future__ import annotations


from sqlalchemy import Numeric, inspect as sa_inspect

from app.models.pedido_compra import PedidoCompra


class TestPedidoCompraModelF5:
    """T5.3 — PedidoCompra model has tipo_cambio_manual Numeric(18,6) nullable."""

    def test_has_tipo_cambio_manual_column(self) -> None:
        mapper = sa_inspect(PedidoCompra)
        col_names = [col.key for col in mapper.columns]
        assert "tipo_cambio_manual" in col_names

    def test_tipo_cambio_manual_is_numeric(self) -> None:
        mapper = sa_inspect(PedidoCompra)
        col = mapper.columns["tipo_cambio_manual"]
        assert isinstance(col.type, Numeric)

    def test_tipo_cambio_manual_is_nullable(self) -> None:
        mapper = sa_inspect(PedidoCompra)
        col = mapper.columns["tipo_cambio_manual"]
        assert col.nullable is True

    def test_pedido_instance_tipo_cambio_manual_defaults_none(self) -> None:
        pedido = PedidoCompra()
        assert getattr(pedido, "tipo_cambio_manual", "MISSING") is None
