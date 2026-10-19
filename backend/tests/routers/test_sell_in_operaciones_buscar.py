"""The Compras operation picker of the sell-in create panel (feature sell-in-sell-out T3d).

`GET /api/sell-in/compras/operaciones` searches `pedidos_compra` by any part of
the operation number, its id, the supplier name or the invoice number, newest
first, at most 20. `proveedor_id`/`moneda` narrow it to the operations a sell
in may still combine (same supplier and currency) and `excluir` leaves out the
ones already linked. It needs `sell_in.gestionar` only: an operator with no
Compras permission must still be able to pick.

SQLite test database, like `test_sell_in_operaciones.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor

URL = "/api/sell-in/compras/operaciones"
INICIO = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    # Deliberately NO Compras permission (administracion.ver_ordenes_compra).
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
    """`_nuevo(proveedor, ...)`: each call is one day newer than the previous one."""
    empresa = Empresa(nombre="Gauss", activo=True, orden=0)
    db.add(empresa)
    db.flush()
    contador = iter(range(1, 1000))

    def _nuevo(proveedor: Proveedor, moneda: str = "ARS", numero_factura: str | None = None) -> PedidoCompra:
        n = next(contador)
        row = PedidoCompra(
            numero=f"P-SI-{n:05d}",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda=moneda,
            monto=Decimal("5000.50"),
            estado="aprobado",
            tipo="mercaderia",
            numero_factura=numero_factura,
            creado_por_id=admin_user.id,
            created_at=INICIO + timedelta(days=n),
        )
        db.add(row)
        db.flush()
        return row

    return _nuevo


def _ids(resp) -> list[int]:
    assert resp.status_code == 200, resp.text
    return [op["id"] for op in resp.json()["items"]]


def test_each_option_carries_what_identifies_the_operation(client, gestor, proveedores, nuevo_pedido):
    pedido = nuevo_pedido(proveedores[0], moneda="USD", numero_factura="A-0001-00001234")

    resp = client.get(URL, headers=gestor)

    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == [
        {
            "id": pedido.id,
            "numero": pedido.numero,
            "proveedor_id": proveedores[0].id,
            "proveedor_nombre": "TP-Link",
            "fecha": "2026-10-02",
            "moneda": "USD",
            "monto": "5000.50",
            "estado": "aprobado",
            "numero_factura": "A-0001-00001234",
        }
    ]


def test_without_text_lists_the_newest_first(client, gestor, proveedores, nuevo_pedido):
    viejo, medio, nuevo = (nuevo_pedido(proveedores[0]) for _ in range(3))

    assert _ids(client.get(URL, headers=gestor)) == [nuevo.id, medio.id, viejo.id]


def test_finds_by_any_part_of_the_operation_number(client, gestor, proveedores, nuevo_pedido):
    pedidos = [nuevo_pedido(proveedores[0]) for _ in range(12)]

    assert _ids(client.get(URL, params={"q": "si-00011"}, headers=gestor)) == [pedidos[10].id]


def test_finds_by_the_id_the_chip_shows(client, gestor, proveedores, nuevo_pedido, db):
    pedidos = [nuevo_pedido(proveedores[0]) for _ in range(3)]
    for pedido in pedidos:  # no number holds a digit: only the id can match
        pedido.numero = f"OC-{chr(ord('A') + pedido.id)}"
    db.flush()
    objetivo = pedidos[1]

    assert _ids(client.get(URL, params={"q": str(objetivo.id)}, headers=gestor)) == [objetivo.id]


def test_finds_by_supplier_name_ignoring_case(client, gestor, proveedores, nuevo_pedido):
    tplink = nuevo_pedido(proveedores[0])
    nuevo_pedido(proveedores[1])

    assert _ids(client.get(URL, params={"q": "tp-li"}, headers=gestor)) == [tplink.id]


def test_finds_by_invoice_number(client, gestor, proveedores, nuevo_pedido):
    nuevo_pedido(proveedores[0])
    facturado = nuevo_pedido(proveedores[0], numero_factura="A-0003-00099887")

    assert _ids(client.get(URL, params={"q": "99887"}, headers=gestor)) == [facturado.id]


def test_like_wildcards_in_the_text_are_literal(client, gestor, proveedores, nuevo_pedido):
    nuevo_pedido(proveedores[0])

    assert _ids(client.get(URL, params={"q": "%"}, headers=gestor)) == []


def test_supplier_and_currency_filters_keep_only_what_can_be_combined(client, gestor, proveedores, nuevo_pedido):
    ars = nuevo_pedido(proveedores[0], moneda="ARS")
    nuevo_pedido(proveedores[0], moneda="USD")
    nuevo_pedido(proveedores[1], moneda="ARS")

    params = {"proveedor_id": proveedores[0].id, "moneda": "ARS"}
    assert _ids(client.get(URL, params=params, headers=gestor)) == [ars.id]


def test_already_linked_operations_are_left_out(client, gestor, proveedores, nuevo_pedido):
    p1, p2, p3 = (nuevo_pedido(proveedores[0]) for _ in range(3))

    params = {"excluir": [p1.id, p3.id]}
    assert _ids(client.get(URL, params=params, headers=gestor)) == [p2.id]


def test_answers_at_most_twenty_newest(client, gestor, proveedores, nuevo_pedido):
    pedidos = [nuevo_pedido(proveedores[0]) for _ in range(25)]

    ids = _ids(client.get(URL, headers=gestor))

    assert ids == [p.id for p in reversed(pedidos)][:20]


def test_needs_gestionar_not_compras_permissions(client, lector, proveedores, nuevo_pedido):
    nuevo_pedido(proveedores[0])

    assert client.get(URL, headers=lector).status_code == 403
    assert client.get(URL).status_code in (401, 403)


@pytest.mark.parametrize("q", ["²", "١٢"])
def test_non_ascii_digits_are_plain_text_not_an_id(client, gestor, proveedores, nuevo_pedido, q):
    nuevo_pedido(proveedores[0])

    assert _ids(client.get(URL, params={"q": q}, headers=gestor)) == []
