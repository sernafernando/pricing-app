"""Sell-in purchases linked to several Compras operations (feature sell-in-sell-out T3b-2).

A sell in may reference 0..N operations (`pedidos_compra`): every one must
exist and they must share one supplier and one currency. The sell in's supplier
must be theirs (taken from them when missing); its currency is its own.
`GET /prefill` reads the operations' supplier, currency, first goods-receipt
date and their ordered OC lines (`pedido_compra_ocs` -> `tb_purchase_order_detail`)
so the panel starts from them; the operator can still change everything.

SQLite test database, like `test_sell_in_compras.py`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_ingresos import PedidoCompraIngreso
from app.models.pedido_compra_oc import PedidoCompraOc
from app.models.producto import ProductoERP, TipoMoneda
from app.models.proveedor import Proveedor
from app.models.purchase_order_detail import PurchaseOrderDetail
from app.models.sell_in import SellInCompra, SellInCompraPedido
from app.schemas.sell_in import PEDIDOS_MAX
from app.services.sell_in import compras as compras_service

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


def test_a_sell_in_keeps_its_own_currency_over_the_operations_one(
    client, gestor, productos, proveedores, nuevo_pedido, db
):
    """An ARS credit on USD operations is allowed: the sell in converts costs at its own tipo_cambio."""
    p1, p2 = nuevo_pedido(proveedores[0], moneda="USD"), nuevo_pedido(proveedores[0], moneda="USD")

    resp = client.post(BASE, json=_body(pedido_compra_ids=[p1.id, p2.id], moneda="ARS"), headers=gestor)

    assert resp.status_code == 201, resp.text
    assert resp.json()["moneda"] == "ARS"
    assert _links(db, resp.json()["id"]) == sorted([p1.id, p2.id])


def test_a_second_sync_with_the_same_operations_keeps_every_link(
    client, gestor, productos, proveedores, nuevo_pedido, db
):
    p1, p2 = nuevo_pedido(proveedores[0]), nuevo_pedido(proveedores[0])
    data = client.post(BASE, json=_body(pedido_compra_ids=[p1.id, p2.id]), headers=gestor).json()
    compra = db.get(SellInCompra, data["id"])

    with db.no_autoflush:
        compras_service._sincronizar_pedidos(db, compra, [p1.id, p2.id])
    db.flush()

    assert _links(db, compra.id) == sorted([p1.id, p2.id])


def test_create_accepts_the_operations_own_supplier(client, gestor, productos, proveedores, nuevo_pedido):
    p1 = nuevo_pedido(proveedores[0])

    resp = client.post(BASE, json=_body(pedido_compra_ids=[p1.id], proveedor_id=proveedores[0].id), headers=gestor)

    assert resp.status_code == 201, resp.text
    assert resp.json()["proveedor_id"] == proveedores[0].id


def test_an_operation_only_in_the_column_still_shows(client, gestor, productos, proveedores, nuevo_pedido, db):
    """Rows written before the link table's backfill, or straight to the column, keep their operation."""
    p1 = nuevo_pedido(proveedores[0])
    data = client.post(BASE, json=_body(pedido_compra_ids=[p1.id]), headers=gestor).json()
    db.query(SellInCompraPedido).filter(SellInCompraPedido.compra_id == data["id"]).delete()
    db.flush()

    assert client.get(f"{BASE}/{data['id']}", headers=gestor).json()["pedido_compra_ids"] == [p1.id]


def test_too_many_operations_is_refused_by_the_schema(client, gestor, productos, db):
    resp = client.post(BASE, json=_body(pedido_compra_ids=list(range(1, PEDIDOS_MAX + 2))), headers=gestor)

    assert resp.status_code == 422, resp.text
    assert "pedido_compra_ids" in resp.text
    assert "no existe" not in resp.text
    assert db.query(SellInCompra).count() == 0


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


# ── Prefill ─────────────────────────────────────────────────────────


def _oc(db, pedido: PedidoCompra, poh_id: int, lineas: list[tuple[int | None, str]], *, por_cabecera=False) -> None:
    """An ERP purchase order with `(item_id, pod_qty)` lines, linked to `pedido` through
    `pedido_compra_ocs` or, with `por_cabecera`, only through the header's first-link cache."""
    if por_cabecera:
        pedido.oc_comp_id, pedido.oc_bra_id, pedido.oc_poh_id = 1, 1, poh_id
    else:
        db.add(PedidoCompraOc(pedido_id=pedido.id, oc_comp_id=1, oc_bra_id=1, oc_poh_id=poh_id))
    for pod_id, (item_id, qty) in enumerate(lineas, start=1):
        db.add(
            PurchaseOrderDetail(
                comp_id=1,
                bra_id=1,
                poh_id=poh_id,
                pod_id=pod_id,
                item_id=item_id,
                pod_qty=Decimal(qty),
                pod_confirmedqty=Decimal("1"),
            )
        )
    db.flush()


def _ingreso(db, pedido: PedidoCompra, user, creado: datetime, fecha: date | None = None) -> None:
    db.add(
        PedidoCompraIngreso(
            pedido_id=pedido.id,
            cantidad_recibida=Decimal("1"),
            usuario_id=user.id,
            created_at=creado,
            fecha_ingreso=fecha,
        )
    )
    db.flush()


def _prefill(client, headers, *ids):
    return client.get(f"{BASE}/prefill", params={"pedido_compra_ids": list(ids)}, headers=headers)


def test_prefill_sums_the_ordered_quantity_of_every_oc_line_per_product(
    client, gestor, productos, proveedores, nuevo_pedido, db, admin_user
):
    p1, p2 = nuevo_pedido(proveedores[0]), nuevo_pedido(proveedores[0])
    _oc(db, p1, 9001, [(4513, "5"), (4512, "10"), (None, "3")])
    _oc(db, p1, 9002, [(4512, "2.000000")])
    _oc(db, p2, 9003, [(4513, "7")], por_cabecera=True)
    # 21:00 in Buenos Aires on Oct 3 is already Oct 4 in UTC: the date is the local one.
    _ingreso(db, p2, admin_user, datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc))
    _ingreso(db, p1, admin_user, datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc))

    resp = _prefill(client, gestor, p1.id, p2.id, p1.id)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["pedido_compra_ids"] == [p1.id, p2.id]
    assert (data["proveedor_id"], data["proveedor_nombre"], data["moneda"]) == (proveedores[0].id, "TP-Link", "ARS")
    assert data["fecha_ingreso"] == "2026-10-03"
    assert data["items"] == [
        {"item_id": 4513, "codigo": "SW-16", "descripcion": "Switch 16 bocas", "cantidad": 12},
        {"item_id": 4512, "codigo": "SW-8", "descripcion": "Switch 8 bocas", "cantidad": 12},
    ]


def test_prefill_prefers_a_typed_receipt_date_and_is_null_without_receipts(
    client, gestor, productos, proveedores, nuevo_pedido, db, admin_user
):
    p1, p2 = nuevo_pedido(proveedores[0]), nuevo_pedido(proveedores[0])
    assert _prefill(client, gestor, p1.id).json()["fecha_ingreso"] is None
    assert _prefill(client, gestor, p1.id).json()["items"] == []

    _ingreso(db, p2, admin_user, datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc), fecha=date(2026, 10, 2))

    assert _prefill(client, gestor, p1.id, p2.id).json()["fecha_ingreso"] == "2026-10-02"


def test_prefill_refuses_what_create_refuses(client, gestor, productos, proveedores, nuevo_pedido):
    tp, merc = proveedores
    p1, otro, en_usd = nuevo_pedido(tp), nuevo_pedido(merc), nuevo_pedido(tp, moneda="USD")

    for ids, fragment in [
        ((p1.id, 987654), "987654 no existe"),
        ((p1.id, otro.id), "proveedores distintos"),
        ((p1.id, en_usd.id), "monedas distintas"),
    ]:
        resp = _prefill(client, gestor, *ids)
        assert resp.status_code == 422, resp.text
        assert fragment in _message(resp)
    assert _prefill(client, gestor).status_code == 422


def test_prefill_refuses_too_many_operations_before_reading_them(client, gestor):
    resp = _prefill(client, gestor, *range(1, PEDIDOS_MAX + 2))

    assert resp.status_code == 422, resp.text
    assert "pedido_compra_ids" in resp.text
    assert "no existe" not in resp.text


def test_prefill_needs_gestionar(client, lector, proveedores, nuevo_pedido):
    p1 = nuevo_pedido(proveedores[0])

    assert _prefill(client, lector, p1.id).status_code == 403
    assert client.get(f"{BASE}/prefill", params={"pedido_compra_ids": [p1.id]}).status_code in (401, 403)
