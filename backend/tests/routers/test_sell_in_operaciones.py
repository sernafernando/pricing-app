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

from app.models.auditoria import Auditoria, TipoAccion
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_ingresos import PedidoCompraIngreso
from app.models.pedido_compra_linea_facturada import PedidoCompraLineaFacturada
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


# A product with no invoiced line has no % base.
_SIN_FACTURAR = {"facturado": None, "facturado_moneda": None}


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
        {"item_id": 4513, "codigo": "SW-16", "descripcion": "Switch 16 bocas", "cantidad": 12, **_SIN_FACTURAR},
        {"item_id": 4512, "codigo": "SW-8", "descripcion": "Switch 8 bocas", "cantidad": 12, **_SIN_FACTURAR},
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


def test_prefill_rounds_quantities_half_up_and_drops_products_without_units(
    client, gestor, productos, proveedores, nuevo_pedido, db
):
    """2.1 + 0.4 = 2.5 rounds UP to 3 (banker's rounding would give 2); a product whose lines cancel
    out (a correction line) or round to 0 is left out. A product missing from productos_erp keeps
    its line with no code nor description."""
    p1 = nuevo_pedido(proveedores[0])
    _oc(db, p1, 9101, [(4512, "2.1"), (4513, "5"), (4512, "0.4"), (4513, "-5"), (9999, "1"), (4514, "0.4")])

    assert _prefill(client, gestor, p1.id).json()["items"] == [
        {"item_id": 4512, "codigo": "SW-8", "descripcion": "Switch 8 bocas", "cantidad": 3, **_SIN_FACTURAR},
        {"item_id": 9999, "codigo": None, "descripcion": None, "cantidad": 1, **_SIN_FACTURAR},
    ]


def test_prefill_counts_an_oc_shared_by_two_operations_once(client, gestor, productos, proveedores, nuevo_pedido, db):
    p1, p2 = nuevo_pedido(proveedores[0]), nuevo_pedido(proveedores[0])
    _oc(db, p1, 9201, [(4512, "4")])
    db.add(PedidoCompraOc(pedido_id=p2.id, oc_comp_id=1, oc_bra_id=1, oc_poh_id=9201))
    db.flush()

    assert [i["cantidad"] for i in _prefill(client, gestor, p1.id, p2.id).json()["items"]] == [4]


@pytest.mark.parametrize("enviar", ["post", "prefill"])
def test_the_operations_cap_counts_what_was_sent_not_the_distinct_ids(
    client, gestor, productos, proveedores, nuevo_pedido, enviar
):
    p1 = nuevo_pedido(proveedores[0])
    ids = [p1.id] * (PEDIDOS_MAX + 1)  # the cap counts what was sent, before deduplication

    if enviar == "post":
        resp = client.post(BASE, json=_body(pedido_compra_ids=ids), headers=gestor)
    else:
        resp = _prefill(client, gestor, *ids)

    assert resp.status_code == 422, resp.text
    assert "pedido_compra_ids" in resp.text


def test_prefill_needs_gestionar(client, lector, proveedores, nuevo_pedido):
    p1 = nuevo_pedido(proveedores[0])

    assert _prefill(client, lector, p1.id).status_code == 403
    assert client.get(f"{BASE}/prefill", params={"pedido_compra_ids": [p1.id]}).status_code in (401, 403)


# ── Products of one operation (the picker's hover popover, T3f) ─────


def _productos(client, headers, pedido_id: int):
    return client.get(f"{BASE}/operaciones/{pedido_id}/productos", headers=headers)


def _recibidas(db, poh_id: int, por_linea: dict[int, str]) -> None:
    for linea in db.query(PurchaseOrderDetail).filter(PurchaseOrderDetail.poh_id == poh_id):
        linea.pod_confirmedqty = Decimal(por_linea.get(linea.pod_id, "0"))
    db.flush()


def test_productos_lists_ordered_and_received_units_per_product(
    client, gestor, productos, proveedores, nuevo_pedido, db
):
    pedido = nuevo_pedido(proveedores[0])
    _oc(db, pedido, 9301, [(4513, "5"), (4512, "10"), (None, "3")])
    _oc(db, pedido, 9302, [(4512, "2.4"), (9999, "1"), (8888, "0.2")])
    _recibidas(db, 9301, {1: "2", 2: "10"})
    _recibidas(db, 9302, {1: "0.5"})

    resp = _productos(client, gestor, pedido.id)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "items": [
            {"item_id": 4513, "codigo": "SW-16", "descripcion": "Switch 16 bocas", "pedida": 5, "recibida": 2},
            {"item_id": 4512, "codigo": "SW-8", "descripcion": "Switch 8 bocas", "pedida": 12, "recibida": 11},
            {"item_id": 9999, "codigo": None, "descripcion": None, "pedida": 1, "recibida": 0},
        ]
    }


def test_productos_reads_the_header_link_and_is_empty_without_oc(
    client, gestor, productos, proveedores, nuevo_pedido, db
):
    sin_oc, por_cabecera = nuevo_pedido(proveedores[0]), nuevo_pedido(proveedores[0])
    _oc(db, por_cabecera, 9303, [(4512, "4")], por_cabecera=True)

    assert _productos(client, gestor, sin_oc.id).json() == {"items": []}
    assert [i["item_id"] for i in _productos(client, gestor, por_cabecera.id).json()["items"]] == [4512]


def test_productos_of_an_unknown_operation_is_a_404(client, gestor):
    resp = _productos(client, gestor, 987654)

    assert resp.status_code == 404
    assert "987654" in _message(resp)


def test_productos_needs_gestionar_like_the_picker(client, lector, proveedores, nuevo_pedido):
    pedido = nuevo_pedido(proveedores[0])

    assert _productos(client, lector, pedido.id).status_code == 403
    assert client.get(f"{BASE}/operaciones/{pedido.id}/productos").status_code in (401, 403)


def test_productos_query_count_does_not_grow_with_the_lines(client, gestor, productos, proveedores, nuevo_pedido, db):
    from sqlalchemy import event

    chico, grande = nuevo_pedido(proveedores[0]), nuevo_pedido(proveedores[0])
    _oc(db, chico, 9304, [(4512, "1")])
    _oc(db, grande, 9305, [(4512, "1"), (4513, "2")])
    _oc(db, grande, 9306, [(4513, "1"), (4512, "3")])

    def _contar(pedido_id: int) -> int:
        sentencias: list[str] = []
        registrar = lambda *args: sentencias.append(args[2])  # noqa: E731
        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", registrar)
        try:
            assert _productos(client, gestor, pedido_id).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", registrar)
        return sum(1 for s in sentencias if "purchase_order_detail" in s or "productos_erp" in s)

    assert _contar(grande.id) == _contar(chico.id) == 2


# ── Sell in as a percentage of the invoiced net (T3g-3) ─────────────


def _facturado(db, pedido: PedidoCompra, item_id: int, importe: str | None, moneda: str | None = "ARS") -> None:
    db.add(
        PedidoCompraLineaFacturada(
            pedido_id=pedido.id,
            item_id=item_id,
            cantidad=10,
            importe_neto=None if importe is None else Decimal(importe),
            moneda=moneda,
        )
    )
    db.flush()


def _porcentaje(pedidos, **overrides) -> dict:
    body = _body(tipo="porcentaje", porcentaje="2.5", pedido_compra_ids=[p.id for p in pedidos])
    del body["monto_total"], body["formula"]
    body.update(overrides)
    return body


@pytest.fixture()
def facturadas(db, proveedores, nuevo_pedido):
    """Two operations: 4512 invoiced 10101.00 on the first, 4513 invoiced 2000.00 + 1000.00 on both."""
    p1, p2 = nuevo_pedido(proveedores[0]), nuevo_pedido(proveedores[0])
    _facturado(db, p1, 4512, "10101.00")
    _facturado(db, p1, 4513, "2000.00")
    _facturado(db, p2, 4513, "1000.00")
    return p1, p2


def test_a_percentage_purchase_takes_each_line_amount_from_its_invoiced_net(client, gestor, productos, facturadas, db):
    resp = client.post(BASE, json=_porcentaje(facturadas), headers=gestor)

    assert resp.status_code == 201, resp.text
    data = resp.json()
    # 10101.00 x 2.5% = 252.525 -> 252.53 (half up); (2000 + 1000) x 2.5% = 75.00
    assert [(i["item_id"], i["monto_asignado"]) for i in data["items"]] == [(4512, "252.53"), (4513, "75.00")]
    assert (data["tipo"], data["porcentaje"], data["monto_total"], data["formula"]) == (
        "porcentaje",
        "2.5000",
        "327.53",
        "manual",
    )
    compra = db.get(SellInCompra, data["id"])
    assert (compra.tipo, compra.porcentaje, compra.monto_total) == ("porcentaje", Decimal("2.5"), Decimal("327.53"))
    auditadas = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_COMPRA_CREADA).all()
    assert {(a.valores_nuevos["tipo"], a.valores_nuevos["porcentaje"]) for a in auditadas} == {("porcentaje", "2.5")}


def test_a_percentage_preview_shows_the_same_split_and_its_base_without_writing(
    client, gestor, productos, facturadas, db
):
    body = _porcentaje(facturadas)
    del body["fecha_compra"]

    resp = client.post(f"{BASE}/preview", json=body, headers=gestor)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (data["tipo"], data["porcentaje"], data["monto_total"], data["formula"]) == (
        "porcentaje",
        "2.5",
        "327.53",
        "manual",
    )
    assert [(f["item_id"], f["base_facturada"], f["monto_asignado"]) for f in data["lineas"]] == [
        (4512, "10101.00", "252.53"),
        (4513, "3000.00", "75.00"),
    ]
    assert db.query(SellInCompra).count() == 0


def test_a_fixed_amount_purchase_is_unchanged_and_has_no_percentage(client, gestor, productos, db):
    resp = client.post(BASE, json=_body(), headers=gestor)

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert (data["tipo"], data["porcentaje"], data["monto_total"], data["formula"]) == (
        "monto",
        None,
        "1000.00",
        "proporcional",
    )
    assert [i["monto_asignado"] for i in data["items"]] == ["250.00", "750.00"]
    preview = client.post(f"{BASE}/preview", json=_body(), headers=gestor).json()
    assert [f["base_facturada"] for f in preview["lineas"]] == [None, None]
    auditada = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_COMPRA_CREADA).first()
    assert "tipo" not in auditada.valores_nuevos and "porcentaje" not in auditada.valores_nuevos


@pytest.mark.parametrize(
    ("cambios", "fragmento"),
    [
        ({"monto_total": "100.00"}, "calcula su monto"),
        ({"formula": "proporcional"}, "calcula su monto"),
        ({"porcentaje": None}, "Falta el porcentaje"),
        ({"porcentaje": "0"}, "entre 0 y 100"),
        ({"porcentaje": "100.0001"}, "entre 0 y 100"),
        ({"porcentaje": "2.00001"}, "4 decimales"),
        ({"pedido_compra_ids": []}, "necesita sus operaciones"),
        ({"lineas": [{"item_id": 4512, "cantidad": 10, "monto_manual": "5.00"}]}, "calcula su monto"),
        ({"moneda": "USD", "tipo_cambio": "1400"}, "está en ARS y la compra en USD"),
    ],
)
def test_a_percentage_purchase_refuses_what_does_not_fit(client, gestor, productos, facturadas, db, cambios, fragmento):
    resp = client.post(BASE, json=_porcentaje(facturadas, **cambios), headers=gestor)

    assert resp.status_code == 422, resp.text
    assert fragmento in _message(resp)
    assert db.query(SellInCompra).count() == 0


def test_a_fixed_amount_purchase_needs_its_total_and_takes_no_percentage(client, gestor, productos, db):
    sin_total = _body()
    del sin_total["monto_total"]
    resp = client.post(BASE, json=sin_total, headers=gestor)
    assert resp.status_code == 422 and "Falta el monto total" in _message(resp)

    resp = client.post(BASE, json=_body(porcentaje="2"), headers=gestor)
    assert resp.status_code == 422 and "no lleva porcentaje" in _message(resp)
    assert db.query(SellInCompra).count() == 0


@pytest.mark.parametrize(
    ("filas", "fragmento"),
    [
        ([], "no tiene facturado"),  # 4513 never invoiced
        ([(None, None)], "mezcla monedas"),  # one invoice mixes currencies
        ([("1000.00", "ARS"), ("50.00", "USD")], "mezcla monedas"),  # each operation in another currency
    ],
)
def test_a_percentage_purchase_needs_one_invoiced_net_per_line(
    client, gestor, productos, proveedores, nuevo_pedido, db, filas, fragmento
):
    p1, p2 = nuevo_pedido(proveedores[0]), nuevo_pedido(proveedores[0])
    _facturado(db, p1, 4512, "10101.00")
    for pedido, (importe, moneda) in zip((p1, p2), filas):
        _facturado(db, pedido, 4513, importe, moneda)

    resp = client.post(BASE, json=_porcentaje([p1, p2]), headers=gestor)

    assert resp.status_code == 422, resp.text
    assert fragmento in _message(resp) and "4513" in _message(resp)


def test_prefill_shows_each_products_invoiced_net_and_its_currency(
    client, gestor, productos, proveedores, nuevo_pedido, db
):
    p1, p2 = nuevo_pedido(proveedores[0]), nuevo_pedido(proveedores[0])
    _oc(db, p1, 9101, [(4512, "10"), (4513, "5")])
    _oc(db, p2, 9102, [(4513, "5")])
    _facturado(db, p1, 4512, "10101.00")
    _facturado(db, p1, 4513, None, None)  # mixes currencies: no single amount
    _facturado(db, p2, 4513, "1000.00")

    data = _prefill(client, gestor, p1.id, p2.id).json()

    assert [(i["item_id"], i["facturado"], i["facturado_moneda"]) for i in data["items"]] == [
        (4512, "10101.00", "ARS"),
        (4513, None, None),
    ]
