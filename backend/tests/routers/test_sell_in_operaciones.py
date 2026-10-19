"""Sell-in purchases linked to several Compras operations (feature sell-in-sell-out T3b-2).

A sell in may reference 0..N operations (`pedidos_compra`): every one must
exist and they must share supplier and currency, which the sell in must match.
`GET /prefill` reads the operations' supplier, currency, first goods-receipt
date and their ordered OC lines (`pedido_compra_ocs` -> `tb_purchase_order_detail`)
so the panel starts from them; the operator can still change everything.

SQLite test database, like `test_sell_in_compras.py`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.producto import ProductoERP, TipoMoneda
from app.models.proveedor import Proveedor
from app.models.sell_in import SellInCompra, SellInCompraPedido

BASE = "/api/sell-in/compras"


def _message(resp) -> str:
    message = resp.json()["error"]["message"]
    assert isinstance(message, str) and message
    return message


@pytest.fixture()
def productos(db):
    rows = [
        ProductoERP(
            item_id=4512, codigo="SW-8", descripcion="Switch 8 bocas", costo=100.0, moneda_costo=TipoMoneda.ARS
        ),
        ProductoERP(
            item_id=4513, codigo="SW-16", descripcion="Switch 16 bocas", costo=300.0, moneda_costo=TipoMoneda.ARS
        ),
    ]
    db.add_all(rows)
    db.flush()
    return rows


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_in.ver")
    grant_permiso(rol_admin, "sell_in.gestionar")
    return admin_auth_headers


@pytest.fixture()
def lector(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_in.ver")
    return admin_auth_headers


@pytest.fixture()
def proveedores(db):
    rows = [Proveedor(nombre="TP-Link"), Proveedor(nombre="Mercusys")]
    db.add_all(rows)
    db.flush()
    return rows


@pytest.fixture()
def nuevo_pedido(db, admin_user):
    empresa = Empresa(nombre="Gauss", activo=True, orden=0)
    db.add(empresa)
    db.flush()
    contador = iter(range(1, 100))

    def _nuevo(proveedor: Proveedor, moneda: str = "ARS") -> PedidoCompra:
        row = PedidoCompra(
            numero=f"P-SI-{next(contador):05d}",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda=moneda,
            monto=Decimal("5000"),
            estado="aprobado",
            tipo="mercaderia",
            creado_por_id=admin_user.id,
        )
        db.add(row)
        db.flush()
        return row

    return _nuevo


def _body(**overrides) -> dict:
    body = {
        "moneda": "ARS",
        "monto_total": "1000.00",
        "formula": "proporcional",
        "lineas": [{"item_id": 4512, "cantidad": 10}, {"item_id": 4513, "cantidad": 10}],
        "fecha_compra": "2026-10-01",
    }
    body.update(overrides)
    return body


def _links(db, compra_id: int) -> list[int]:
    rows = db.query(SellInCompraPedido).filter(SellInCompraPedido.compra_id == compra_id)
    return sorted(row.pedido_compra_id for row in rows)


# ── Create with several operations ──────────────────────────────────


def test_create_links_every_operation_once_and_keeps_the_first_in_the_column(
    client, gestor, productos, proveedores, nuevo_pedido, db
):
    p1, p2 = nuevo_pedido(proveedores[0]), nuevo_pedido(proveedores[0])

    resp = client.post(BASE, json=_body(pedido_compra_ids=[p1.id, p2.id, p1.id]), headers=gestor)

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert _links(db, data["id"]) == sorted([p1.id, p2.id])
    assert db.get(SellInCompra, data["id"]).pedido_compra_id == p1.id
    assert data["pedido_compra_id"] == p1.id
    assert data["pedido_compra_ids"] == sorted([p1.id, p2.id])
    detalle = client.get(f"{BASE}/{data['id']}", headers=gestor).json()
    assert detalle["pedido_compra_ids"] == sorted([p1.id, p2.id])
    fila = client.get(BASE, headers=gestor).json()["items"][0]
    assert fila["pedido_compra_ids"] == sorted([p1.id, p2.id])


def test_create_takes_the_operations_supplier_when_none_is_sent(
    client, gestor, productos, proveedores, nuevo_pedido, db
):
    p1 = nuevo_pedido(proveedores[0])

    data = client.post(BASE, json=_body(pedido_compra_ids=[p1.id]), headers=gestor).json()

    assert data["proveedor_id"] == proveedores[0].id


def test_legacy_single_operation_is_a_one_element_list(client, gestor, productos, proveedores, nuevo_pedido, db):
    p1 = nuevo_pedido(proveedores[0])

    data = client.post(BASE, json=_body(pedido_compra_id=p1.id), headers=gestor).json()

    assert data["pedido_compra_ids"] == [p1.id]
    assert _links(db, data["id"]) == [p1.id]


def test_legacy_id_inside_the_list_is_accepted_and_goes_to_the_column(
    client, gestor, productos, proveedores, nuevo_pedido, db
):
    p1, p2 = nuevo_pedido(proveedores[0]), nuevo_pedido(proveedores[0])

    resp = client.post(BASE, json=_body(pedido_compra_id=p2.id, pedido_compra_ids=[p1.id, p2.id]), headers=gestor)

    assert resp.status_code == 201, resp.text
    assert resp.json()["pedido_compra_id"] == p2.id
    assert _links(db, resp.json()["id"]) == sorted([p1.id, p2.id])


def test_one_operation_may_feed_several_sell_ins(client, gestor, productos, proveedores, nuevo_pedido, db):
    p1 = nuevo_pedido(proveedores[0])

    for _ in range(2):
        assert client.post(BASE, json=_body(pedido_compra_ids=[p1.id]), headers=gestor).status_code == 201
    assert db.query(SellInCompraPedido).filter(SellInCompraPedido.pedido_compra_id == p1.id).count() == 2


def _rechazos(proveedores, nuevo_pedido):
    """(body overrides, message fragment) for every rule a set of operations can break."""
    tp, merc = proveedores
    p1, p2 = nuevo_pedido(tp), nuevo_pedido(tp)
    otro_proveedor, en_usd = nuevo_pedido(merc), nuevo_pedido(tp, moneda="USD")
    return [
        ({"pedido_compra_ids": [p1.id, 987654]}, "pedido de compra 987654 no existe"),
        ({"pedido_compra_id": p2.id, "pedido_compra_ids": [p1.id]}, f"pedido de compra {p2.id} no figura"),
        ({"pedido_compra_ids": [p1.id, otro_proveedor.id]}, "proveedores distintos"),
        ({"pedido_compra_ids": [p1.id, en_usd.id]}, "monedas distintas"),
        ({"pedido_compra_ids": [p1.id], "proveedor_id": merc.id}, "proveedor de la compra no coincide"),
        ({"pedido_compra_ids": [p1.id], "moneda": "USD", "tipo_cambio": "1000"}, "moneda de la compra (USD)"),
    ]


def test_create_refuses_operations_that_do_not_fit_and_writes_nothing(
    client, gestor, productos, proveedores, nuevo_pedido, db
):
    for overrides, fragment in _rechazos(proveedores, nuevo_pedido):
        resp = client.post(BASE, json=_body(**overrides), headers=gestor)

        assert resp.status_code == 422, (overrides, resp.text)
        assert fragment in _message(resp), (overrides, _message(resp))
    assert db.query(SellInCompra).count() == 0
    assert db.query(SellInCompraPedido).count() == 0
