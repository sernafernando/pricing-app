"""SoT helpers for pedido ↔ ERP invoice M:N links."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_factura import (
    PedidoCompraFactura,
    count_pedidos_for_ct,
    cts_for_pedido,
)
from app.models.proveedor import OrigenProveedor, Proveedor


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=1, nombre="EmpFactSot", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=1,
        nombre="ProvFactSot",
        origen=OrigenProveedor.MANUAL,
        activo=True,
        supp_id=55,
    )
    db.add(p)
    db.flush()
    return p


def _pedido(db, empresa, proveedor, user_id: int, *, ct=None, fecha=None) -> PedidoCompra:
    p = PedidoCompra(
        numero="P-SOT-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("100"),
        estado="aprobado",
        ct_transaction_id=ct,
        fecha_factura=fecha,
        creado_por_id=user_id,
    )
    db.add(p)
    db.flush()
    return p


def test_cts_for_pedido_falls_back_to_header(db, empresa, proveedor, active_user):
    pedido = _pedido(db, empresa, proveedor, active_user.id, ct=9001, fecha=date(2026, 1, 2))
    assert cts_for_pedido(db, pedido) == [(9001, date(2026, 1, 2))]


def test_cts_for_pedido_prefers_junction(db, empresa, proveedor, active_user):
    pedido = _pedido(db, empresa, proveedor, active_user.id, ct=9001, fecha=date(2026, 1, 2))
    db.add(
        PedidoCompraFactura(
            pedido_id=pedido.id,
            ct_transaction_id=9002,
            fecha_factura=date(2026, 2, 3),
        )
    )
    db.add(
        PedidoCompraFactura(
            pedido_id=pedido.id,
            ct_transaction_id=9003,
            fecha_factura=None,
        )
    )
    db.flush()
    assert cts_for_pedido(db, pedido) == [(9002, date(2026, 2, 3)), (9003, None)]


def test_count_pedidos_for_ct_junction(db, empresa, proveedor, active_user):
    a = _pedido(db, empresa, proveedor, active_user.id)
    b = PedidoCompra(
        numero="P-SOT-00002",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("50"),
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(b)
    db.flush()
    db.add(PedidoCompraFactura(pedido_id=a.id, ct_transaction_id=777))
    db.add(PedidoCompraFactura(pedido_id=b.id, ct_transaction_id=777))
    db.flush()
    assert count_pedidos_for_ct(db, 777) == 2
