"""Sell-in purchases API (`/api/sell-in/compras`), feature sell-in-sell-out T2.

Runs on the SQLite test database like the offsets routers: the sell-in tables
are plain tables (their CHECK/UNIQUE rules are already proven on Postgres by
`tests/models/test_sell_in_schema_postgres.py`), and the endpoints only use
portable SQL.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.producto import ProductoERP, TipoMoneda
from app.models.proveedor import Proveedor
from app.models.sell_in import SellInBonoMarca, SellInCompra, SellInCompraItem, SellInCompraPedido, SellInConsumo
from app.services.sell_in import compras as compras_service

BASE = "/api/sell-in/compras"
VER = "sell_in.ver"
GESTIONAR = "sell_in.gestionar"


def D(value) -> Decimal:
    return Decimal(str(value))


def _message(resp) -> str:
    """The readable message of an error, inside the repo's standard envelope (`app.core.exceptions`)."""
    message = resp.json()["error"]["message"]
    assert isinstance(message, str) and message
    return message


@pytest.fixture()
def productos(db):
    rows = [
        ProductoERP(
            item_id=4512,
            codigo="SW-8",
            descripcion="Switch 8 bocas",
            marca="TP-Link",
            costo=100.0,
            moneda_costo=TipoMoneda.ARS,
        ),
        ProductoERP(
            item_id=4513,
            codigo="SW-16",
            descripcion="Switch 16 bocas",
            marca="Mercusys",
            costo=300.0,
            moneda_costo=TipoMoneda.ARS,
        ),
        ProductoERP(
            item_id=4514,
            codigo="AP-1",
            descripcion="Access point",
            marca="Ubiquiti",
            costo=10.0,
            moneda_costo=TipoMoneda.USD,
        ),
        ProductoERP(item_id=4515, codigo="SC-0", descripcion="Sin costo", costo=None, moneda_costo=TipoMoneda.ARS),
    ]
    db.add_all(rows)
    db.flush()
    return {row.item_id: row for row in rows}


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VER)
    grant_permiso(rol_admin, GESTIONAR)
    return admin_auth_headers


@pytest.fixture()
def lector(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VER)
    return admin_auth_headers


def _preview_body(**overrides) -> dict:
    body = {
        "moneda": "ARS",
        "monto_total": "1000.00",
        "formula": "proporcional",
        "lineas": [{"item_id": 4512, "cantidad": 10}, {"item_id": 4513, "cantidad": 10}],
    }
    body.update(overrides)
    return body


def _create_body(**overrides) -> dict:
    body = _preview_body(fecha_compra="2026-10-01", descripcion="Bonificación Q4 switches")
    body.update(overrides)
    return body


def _crear(client, headers, **overrides) -> dict:
    resp = client.post(BASE, json=_create_body(**overrides), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Permissions ─────────────────────────────────────────────────────


ENDPOINTS = [
    ("post", f"{BASE}/preview", _preview_body()),
    ("post", BASE, _create_body()),
    ("get", BASE, None),
    ("get", f"{BASE}/resumen", None),
    ("get", f"{BASE}/1", None),
    ("post", f"{BASE}/1/anular", {}),
    ("post", f"{BASE}/anular-masivo", {"ids": [1]}),
]


@pytest.mark.parametrize("method,url,body", ENDPOINTS)
def test_every_endpoint_requires_a_permission(client, auth_headers, productos, method, url, body):
    kwargs = {"headers": auth_headers}
    if body is not None:
        kwargs["json"] = body
    resp = getattr(client, method)(url, **kwargs)
    assert resp.status_code == 403


@pytest.mark.parametrize("method,url,body", ENDPOINTS)
def test_every_endpoint_requires_authentication(client, productos, method, url, body):
    resp = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
    assert resp.status_code in (401, 403)


@pytest.mark.parametrize(
    "method,url,body",
    [e for e in ENDPOINTS if e[0] == "post"],
)
def test_writes_need_gestionar_not_just_ver(client, lector, productos, method, url, body):
    resp = getattr(client, method)(url, json=body, headers=lector)
    assert resp.status_code == 403


def test_ver_is_enough_to_read(client, lector):
    assert client.get(BASE, headers=lector).status_code == 200


# ── Preview ─────────────────────────────────────────────────────────


def test_preview_splits_proportionally_to_current_cost(client, gestor, productos, db):
    resp = client.post(f"{BASE}/preview", json=_preview_body(), headers=gestor)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    first, second = data["lineas"]
    assert first["item_id"] == 4512
    assert first["codigo"] == "SW-8"
    assert first["descripcion"] == "Switch 8 bocas"
    assert D(first["costo_base_unit"]) == D("100")
    assert D(first["monto_asignado"]) == D("250.00")
    assert D(first["descuento_unit"]) == D("25")
    assert D(first["costo_con_sell_in_unit"]) == D("75")
    assert D(first["porcentaje"]) == D("25.00")
    assert D(second["monto_asignado"]) == D("750.00")
    assert D(second["costo_con_sell_in_unit"]) == D("225")

    totales = data["totales"]
    assert totales["cantidad"] == 20
    assert D(totales["costo_base_total"]) == D("4000")
    assert D(totales["monto_asignado_total"]) == D("1000.00")
    assert D(totales["costo_con_sell_in_total"]) == D("3000")
    assert D(totales["porcentaje"]) == D("25.00")

    assert db.query(SellInCompra).count() == 0
    assert db.query(SellInCompraItem).count() == 0


def test_preview_converts_usd_cost_into_an_ars_purchase(client, gestor, productos):
    body = _preview_body(tipo_cambio="1000", lineas=[{"item_id": 4514, "cantidad": 2}], monto_total="2000.00")
    resp = client.post(f"{BASE}/preview", json=body, headers=gestor)

    assert resp.status_code == 200, resp.text
    (linea,) = resp.json()["lineas"]
    assert D(linea["costo_base_unit"]) == D("10000")
    assert D(linea["descuento_unit"]) == D("1000")
    assert D(linea["porcentaje"]) == D("10.00")


def test_preview_converts_ars_cost_into_a_usd_purchase(client, gestor, productos):
    body = _preview_body(
        moneda="USD", tipo_cambio="1000", monto_total="1.00", lineas=[{"item_id": 4512, "cantidad": 10}]
    )
    resp = client.post(f"{BASE}/preview", json=body, headers=gestor)

    assert resp.status_code == 200, resp.text
    (linea,) = resp.json()["lineas"]
    assert D(linea["costo_base_unit"]) == D("0.1")
    assert D(linea["descuento_unit"]) == D("0.1")
    assert D(linea["costo_con_sell_in_unit"]) == D("0")


def test_preview_takes_a_client_cost_override_per_line(client, gestor, productos):
    body = _preview_body(
        lineas=[{"item_id": 4512, "cantidad": 10, "costo_base_unit": "300"}, {"item_id": 4513, "cantidad": 10}]
    )
    resp = client.post(f"{BASE}/preview", json=body, headers=gestor)

    assert resp.status_code == 200, resp.text
    first, second = resp.json()["lineas"]
    assert D(first["costo_base_unit"]) == D("300")
    assert D(first["monto_asignado"]) == D("500.00")
    assert D(second["monto_asignado"]) == D("500.00")


def test_preview_override_lets_a_product_without_cost_in(client, gestor, productos):
    body = _preview_body(formula="por_unidad", lineas=[{"item_id": 4515, "cantidad": 4, "costo_base_unit": "0"}])
    resp = client.post(f"{BASE}/preview", json=body, headers=gestor)

    assert resp.status_code == 200, resp.text
    (linea,) = resp.json()["lineas"]
    assert D(linea["monto_asignado"]) == D("1000.00")
    assert linea["porcentaje"] is None


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"lineas": [{"item_id": 4514, "cantidad": 1}]}, "tipo de cambio"),
        ({"moneda": "USD", "lineas": [{"item_id": 4514, "cantidad": 1}]}, "tipo de cambio"),
        ({"tipo_cambio": "0"}, "tipo de cambio"),
        ({"lineas": [{"item_id": 999999, "cantidad": 1}]}, "999999"),
        ({"lineas": [{"item_id": 4515, "cantidad": 1}]}, "costo"),
        ({"lineas": [{"item_id": 4512, "cantidad": 0}]}, "cantidad"),
        ({"lineas": [{"item_id": 4512, "cantidad": 1}, {"item_id": 4512, "cantidad": 2}]}, "duplicado"),
        ({"lineas": []}, "vacía"),
        ({"monto_total": "-5"}, "monto total"),
        (
            {
                "formula": "manual",
                "lineas": [
                    {"item_id": 4512, "cantidad": 1, "monto_manual": "100"},
                    {"item_id": 4513, "cantidad": 1, "monto_manual": "100"},
                ],
            },
            "no coincide",
        ),
        ({"formula": "manual"}, "monto manual"),
    ],
)
def test_preview_domain_errors_are_422_with_spanish_detail(client, gestor, productos, overrides, fragment):
    resp = client.post(f"{BASE}/preview", json=_preview_body(**overrides), headers=gestor)

    assert resp.status_code == 422, resp.text
    detail = _message(resp)
    assert fragment.lower() in detail.lower()


# ── Create ──────────────────────────────────────────────────────────


def test_create_freezes_the_split_and_the_cost(client, gestor, productos, admin_user, db):
    data = _crear(client, gestor, proveedor_id=None)

    assert data["estado"] == "activa"
    assert data["usuario_id"] == admin_user.id
    assert data["formula"] == "proporcional"
    assert D(data["monto_total"]) == D("1000.00")
    assert [i["item_id"] for i in data["items"]] == [4512, 4513]
    assert [D(i["monto_asignado"]) for i in data["items"]] == [D("250.00"), D("750.00")]
    assert [D(i["costo_base_unit"]) for i in data["items"]] == [D("100"), D("300")]

    compra = db.get(SellInCompra, data["id"])
    assert compra.usuario_id == admin_user.id
    assert compra.descripcion == "Bonificación Q4 switches"
    assert sorted(D(i.monto_asignado) for i in db.query(SellInCompraItem).filter_by(compra_id=compra.id)) == [
        D("250.00"),
        D("750.00"),
    ]

    # The cost is frozen: a later cost change does not move the saved purchase.
    productos[4512].costo = 999.0
    db.flush()
    item = db.query(SellInCompraItem).filter_by(compra_id=compra.id, item_id=4512).one()
    assert D(item.costo_base_unit) == D("100")


def test_create_ignores_a_client_monto_asignado_and_recomputes(client, gestor, productos):
    body = _create_body(
        lineas=[{"item_id": 4512, "cantidad": 10, "monto_asignado": "1"}, {"item_id": 4513, "cantidad": 10}]
    )
    resp = client.post(BASE, json=body, headers=gestor)

    assert resp.status_code == 201, resp.text
    assert [D(i["monto_asignado"]) for i in resp.json()["items"]] == [D("250.00"), D("750.00")]


def test_create_writes_one_audit_row_per_line(client, gestor, productos, admin_user, db):
    data = _crear(client, gestor)

    rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_COMPRA_CREADA).all()
    assert sorted(r.item_id for r in rows) == [4512, 4513]
    assert {r.usuario_id for r in rows} == {admin_user.id}
    assert {r.valores_nuevos["compra_id"] for r in rows} == {data["id"]}


def test_create_with_a_domain_error_writes_nothing(client, gestor, productos, db):
    resp = client.post(BASE, json=_create_body(lineas=[{"item_id": 999999, "cantidad": 1}]), headers=gestor)

    assert resp.status_code == 422
    assert _message(resp)
    assert db.query(SellInCompra).count() == 0
    assert db.query(Auditoria).count() == 0


def test_create_from_goods_receipt_needs_its_date(client, gestor, productos):
    resp = client.post(BASE, json=_create_body(cuenta_desde="ingreso"), headers=gestor)

    assert resp.status_code == 422
    assert "fecha de ingreso" in _message(resp).lower()


# ── Supplier and purchase-order references ─────────────────────────


@pytest.fixture()
def proveedor(db):
    row = Proveedor(nombre="TP-Link")
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def pedido(db, proveedor, admin_user):
    empresa = Empresa(nombre="Gauss", activo=True, orden=0)
    db.add(empresa)
    db.flush()
    row = PedidoCompra(
        numero="P-SI-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=D("5000"),
        estado="aprobado",
        tipo="mercaderia",
        creado_por_id=admin_user.id,
    )
    db.add(row)
    db.flush()
    return row


def test_create_keeps_a_known_supplier_and_purchase_order(client, gestor, productos, proveedor, pedido, db):
    data = _crear(client, gestor, proveedor_id=proveedor.id, pedido_compra_id=pedido.id)

    compra = db.get(SellInCompra, data["id"])
    assert compra.proveedor_id == proveedor.id
    assert _links(db, data["id"]) == [pedido.id]  # the link table is the only source (T3b-4; the column is gone)


def _links(db, compra_id: int) -> list[int]:
    rows = db.query(SellInCompraPedido).filter(SellInCompraPedido.compra_id == compra_id)
    return sorted(row.pedido_compra_id for row in rows)


def test_create_links_the_purchase_order(client, gestor, productos, pedido, db):
    data = _crear(client, gestor, pedido_compra_id=pedido.id)

    assert _links(db, data["id"]) == [pedido.id]
    assert client.get(f"{BASE}/{data['id']}", headers=gestor).json()["pedido_compra_id"] == pedido.id


def test_create_without_purchase_order_writes_no_link(client, gestor, productos, db):
    data = _crear(client, gestor)

    assert _links(db, data["id"]) == []


def test_syncing_the_links_follows_the_column(client, gestor, productos, pedido, db):
    """The link rows follow the ids given: none, no links; one again, exactly one."""
    data = _crear(client, gestor, pedido_compra_id=pedido.id)
    compra = db.get(SellInCompra, data["id"])

    compras_service._sincronizar_pedidos(db, compra, [])
    db.flush()
    assert _links(db, compra.id) == []

    compras_service._sincronizar_pedidos(db, compra, [pedido.id])
    compras_service._sincronizar_pedidos(db, compra, [pedido.id])  # idempotent
    db.flush()
    assert _links(db, compra.id) == [pedido.id]


def test_syncing_twice_without_autoflush_adds_one_link(client, gestor, productos, pedido, db):
    """Idempotent on its own, not by relying on the session's autoflush."""
    data = _crear(client, gestor, pedido_compra_id=pedido.id)
    compra = db.get(SellInCompra, data["id"])
    compras_service._sincronizar_pedidos(db, compra, [])
    db.flush()

    with db.no_autoflush:
        compras_service._sincronizar_pedidos(db, compra, [pedido.id])
        compras_service._sincronizar_pedidos(db, compra, [pedido.id])
    db.flush()
    assert _links(db, compra.id) == [pedido.id]


@pytest.mark.parametrize(
    "overrides,fragment",
    [({"proveedor_id": 987654}, "proveedor 987654"), ({"pedido_compra_id": 987654}, "pedido de compra 987654")],
)
def test_create_rejects_unknown_references(client, gestor, productos, db, overrides, fragment):
    resp = client.post(BASE, json=_create_body(**overrides), headers=gestor)

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert fragment in _message(resp)
    assert db.query(SellInCompra).count() == 0


def test_create_turns_an_integrity_error_into_a_422_and_rolls_back(client, gestor, productos, db, monkeypatch):
    """A reference that disappears between the check and the write (a race) is a 422, not a raw 500."""
    monkeypatch.setattr(compras_service, "_validar_referencias", lambda db, data: None)

    resp = client.post(BASE, json=_create_body(proveedor_id=987654), headers=gestor)

    assert resp.status_code == 422, resp.text
    assert "no se pudo guardar" in _message(resp).lower()
    assert db.query(SellInCompra).count() == 0
    assert db.query(SellInCompraItem).count() == 0
    assert db.query(Auditoria).count() == 0


# ── Client cost override ─────────────────────────────────────────


def test_a_negative_cost_override_is_rejected(client, gestor, productos):
    body = _preview_body(lineas=[{"item_id": 4512, "cantidad": 1, "costo_base_unit": "-1"}])
    for url in (f"{BASE}/preview", BASE):
        resp = client.post(url, json={**_create_body(), **body}, headers=gestor)
        assert resp.status_code == 422, resp.text
        assert "negativo" in _message(resp).lower()


def test_a_cost_override_is_rounded_like_product_costs_in_preview_and_record(client, gestor, productos, db):
    lineas = [{"item_id": 4512, "cantidad": 3, "costo_base_unit": "100.12345678"}]
    preview = client.post(f"{BASE}/preview", json=_preview_body(lineas=lineas, monto_total="30.00"), headers=gestor)
    assert preview.status_code == 200, preview.text
    data = _crear(client, gestor, lineas=lineas, monto_total="30.00")

    expected = D("100.123457")  # ROUND_HALF_UP to UNIT_PRECISION (6 decimals)
    assert D(preview.json()["lineas"][0]["costo_base_unit"]) == expected
    assert D(data["items"][0]["costo_base_unit"]) == expected
    item = db.query(SellInCompraItem).filter_by(compra_id=data["id"]).one()
    assert D(item.costo_base_unit) == expected
    assert D(preview.json()["lineas"][0]["costo_con_sell_in_unit"]) == D(data["items"][0]["costo_con_sell_in_unit"])


# ── Consumed units ───────────────────────────────────────────────


def test_serialized_lines_count_consumed_and_remaining_units(client, gestor, productos, db):
    data = _crear(client, gestor)
    ids = {i["item_id"]: i["id"] for i in data["items"]}
    for venta_ref, unidades in ((1, 3), (2, 4)):
        db.add(
            SellInConsumo(
                compra_item_id=ids[4512],
                canal="ml",
                venta_ref=venta_ref,
                item_id=4512,
                fecha_venta=date(2026, 10, 2),
                unidades=unidades,
                descuento_ars=D("25.00") * unidades,
            )
        )
    db.add(
        SellInConsumo(
            compra_item_id=ids[4513],
            canal="fuera",
            venta_ref=9,
            item_id=4513,
            fecha_venta=date(2026, 10, 3),
            unidades=10,
            descuento_ars=D("750.00"),
        )
    )
    db.flush()

    (row,) = compras_service.serializar(db, [db.get(SellInCompra, data["id"])])

    por_item = {i["item_id"]: i for i in row["items"]}
    assert (por_item[4512]["unidades_consumidas"], por_item[4512]["unidades_restantes"]) == (7, 3)
    assert (por_item[4513]["unidades_consumidas"], por_item[4513]["unidades_restantes"]) == (10, 0)
    assert (row["unidades_total"], row["unidades_consumidas"], row["unidades_restantes"]) == (20, 17, 3)


# ── USD purchase ─────────────────────────────────────────────────


def test_create_in_usd_freezes_the_ars_cost_converted_with_its_own_rate(client, gestor, productos, db):
    data = _crear(
        client,
        gestor,
        moneda="USD",
        tipo_cambio="1250.5",
        monto_total="2.00",
        lineas=[{"item_id": 4512, "cantidad": 10}, {"item_id": 4514, "cantidad": 1}],
    )

    compra = db.get(SellInCompra, data["id"])
    assert compra.moneda == "USD"
    assert D(compra.tipo_cambio) == D("1250.5")
    assert (data["moneda"], D(data["tipo_cambio"])) == ("USD", D("1250.5"))
    costos = {i.item_id: D(i.costo_base_unit) for i in db.query(SellInCompraItem).filter_by(compra_id=compra.id)}
    assert costos[4512] == D("0.079968")  # 100 ARS / 1250.5, half up to 6 decimals
    assert costos[4514] == D("10")  # already in USD: not converted


# ── List ────────────────────────────────────────────────────────────


@pytest.fixture()
def tres_compras(client, gestor, productos, db):
    proveedor = Proveedor(nombre="TP-Link")
    db.add(proveedor)
    db.flush()
    a = _crear(client, gestor, fecha_compra="2026-09-01", proveedor_id=proveedor.id)
    b = _crear(client, gestor, fecha_compra="2026-10-01", lineas=[{"item_id": 4513, "cantidad": 5}])
    c = _crear(
        client,
        gestor,
        fecha_compra="2026-10-10",
        lineas=[{"item_id": 4512, "cantidad": 4}],
        descripcion="Rebate octubre",
    )
    anulada = client.post(f"{BASE}/{c['id']}/anular", json={}, headers=gestor)
    assert anulada.status_code == 200, anulada.text
    return {"a": a, "b": b, "c": c, "proveedor_id": proveedor.id}


def _ids(resp) -> list[int]:
    assert resp.status_code == 200, resp.text
    return [row["id"] for row in resp.json()["items"]]


def test_list_is_newest_first_and_paginated(client, gestor, tres_compras):
    t = tres_compras
    resp = client.get(BASE, headers=gestor)
    assert _ids(resp) == [t["c"]["id"], t["b"]["id"], t["a"]["id"]]
    assert resp.json()["total"] == 3

    page2 = client.get(BASE, params={"page": 2, "page_size": 2}, headers=gestor)
    assert _ids(page2) == [t["a"]["id"]]
    assert page2.json()["total"] == 3


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"item_id": 4512}, ["c", "a"]),
        ({"item_id": 4513}, ["b", "a"]),
        ({"estado": "anulada"}, ["c"]),
        ({"estado": "activa"}, ["b", "a"]),
        ({"fecha_desde": "2026-10-01"}, ["c", "b"]),
        ({"fecha_hasta": "2026-10-01"}, ["b", "a"]),
        ({"fecha_desde": "2026-09-15", "fecha_hasta": "2026-10-05"}, ["b"]),
    ],
)
def test_list_filters(client, gestor, tres_compras, params, expected):
    resp = client.get(BASE, params=params, headers=gestor)
    assert _ids(resp) == [tres_compras[k]["id"] for k in expected]


def test_list_filters_by_proveedor(client, gestor, tres_compras):
    resp = client.get(BASE, params={"proveedor_id": tres_compras["proveedor_id"]}, headers=gestor)
    assert _ids(resp) == [tres_compras["a"]["id"]]


def test_list_rows_carry_totals_and_consumed_units(client, gestor, tres_compras, db):
    a = tres_compras["a"]
    item_4512 = next(i for i in a["items"] if i["item_id"] == 4512)
    db.add(
        SellInConsumo(
            compra_item_id=item_4512["id"],
            canal="ml",
            venta_ref=1,
            item_id=4512,
            fecha_venta=date(2026, 10, 2),
            unidades=3,
            descuento_ars=D("75.00"),
        )
    )
    db.flush()

    rows = client.get(BASE, params={"proveedor_id": tres_compras["proveedor_id"]}, headers=gestor).json()["items"]
    (row,) = rows
    assert row["unidades_total"] == 20
    assert row["unidades_consumidas"] == 3
    assert row["unidades_restantes"] == 17
    por_item = {i["item_id"]: i for i in row["items"]}
    assert por_item[4512]["unidades_consumidas"] == 3
    assert por_item[4512]["unidades_restantes"] == 7
    assert por_item[4513]["unidades_consumidas"] == 0
    assert por_item[4513]["unidades_restantes"] == 10


def test_list_rejects_an_unknown_estado(client, gestor):
    assert client.get(BASE, params={"estado": "borrada"}, headers=gestor).status_code == 422


# ── List: aplica, supplier name, text/brand/currency filters ───────


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"aplica": "si"}, ["b", "a"]),
        ({"aplica": "no"}, ["c"]),
        ({"aplica": "todas"}, ["c", "b", "a"]),
        ({}, ["c", "b", "a"]),
    ],
)
def test_list_filters_by_aplica(client, gestor, tres_compras, params, expected):
    resp = client.get(BASE, params=params, headers=gestor)
    assert _ids(resp) == [tres_compras[k]["id"] for k in expected]


def test_list_rejects_an_unknown_aplica(client, gestor):
    assert client.get(BASE, params={"aplica": "quizas"}, headers=gestor).status_code == 422


def test_list_rows_carry_aplica_and_supplier_name(client, gestor, tres_compras):
    rows = {row["id"]: row for row in client.get(BASE, headers=gestor).json()["items"]}
    a, b, c = (rows[tres_compras[k]["id"]] for k in ("a", "b", "c"))
    assert (a["aplica"], b["aplica"], c["aplica"]) == (True, True, False)
    assert a["proveedor_nombre"] == "TP-Link"
    assert b["proveedor_nombre"] is None


def test_detail_carries_aplica_and_supplier_name(client, gestor, tres_compras):
    a = client.get(f"{BASE}/{tres_compras['a']['id']}", headers=gestor).json()
    assert a["aplica"] is True
    assert a["proveedor_nombre"] == "TP-Link"
    c = client.get(f"{BASE}/{tres_compras['c']['id']}", headers=gestor).json()
    assert c["aplica"] is False


@pytest.mark.parametrize(
    "q,expected",
    [
        ("tp-link", ["a"]),  # supplier name, case-insensitive
        ("sw-16", ["b", "a"]),  # an item's product code
        ("16 BOCAS", ["b", "a"]),  # an item's product description
        ("bocas", ["c", "b", "a"]),
        ("rebate", ["c"]),  # the purchase's own reference text
        ("  rebate  ", ["c"]),  # surrounding blanks are ignored
        ("%", []),  # LIKE wildcards are literal
        ("nada que ver", []),
    ],
)
def test_list_free_text_search(client, gestor, tres_compras, q, expected):
    resp = client.get(BASE, params={"q": q}, headers=gestor)
    assert _ids(resp) == [tres_compras[k]["id"] for k in expected]


def test_list_free_text_matches_the_purchase_order_number(client, gestor, productos, pedido):
    con = _crear(client, gestor, pedido_compra_id=pedido.id, descripcion=None)
    _crear(client, gestor, descripcion=None)
    resp = client.get(BASE, params={"q": "p-si-0000"}, headers=gestor)
    assert _ids(resp) == [con["id"]]


def test_list_free_text_finds_the_purchase_order_through_the_link_only(client, gestor, productos, pedido, db):
    """The number is matched over the link rows (T3b-4); the legacy column was dropped (20261217)."""
    solo_link = _crear(client, gestor, descripcion=None)
    db.add(SellInCompraPedido(compra_id=solo_link["id"], pedido_compra_id=pedido.id))
    _crear(client, gestor, descripcion=None)
    db.flush()

    resp = client.get(BASE, params={"q": "p-si-0000"}, headers=gestor)
    assert _ids(resp) == [solo_link["id"]]


@pytest.mark.parametrize(
    "marcas,expected",
    [
        ("TP-Link", ["c", "a"]),
        ("Mercusys", ["b", "a"]),
        ("TP-Link,Mercusys", ["c", "b", "a"]),
        (" TP-Link , Ubiquiti ", ["c", "a"]),
        ("tp-link", []),  # exact match, like the other brand filters
        ("TP", []),
        ("Ubiquiti", []),
    ],
)
def test_list_filters_by_item_brand(client, gestor, tres_compras, marcas, expected):
    resp = client.get(BASE, params={"marcas": marcas}, headers=gestor)
    assert _ids(resp) == [tres_compras[k]["id"] for k in expected]


def test_list_blank_marcas_does_not_filter(client, gestor, tres_compras):
    assert len(_ids(client.get(BASE, params={"marcas": " , "}, headers=gestor))) == 3


def _crear_usd(client, gestor, **overrides) -> dict:
    body = {
        "moneda": "USD",
        "tipo_cambio": "1000",
        "monto_total": "5.50",
        "fecha_compra": "2026-10-05",
        "lineas": [{"item_id": 4514, "cantidad": 3}],
    }
    body.update(overrides)
    return _crear(client, gestor, **body)


def test_list_filters_by_moneda(client, gestor, tres_compras):
    usd = _crear_usd(client, gestor)
    assert _ids(client.get(BASE, params={"moneda": "USD"}, headers=gestor)) == [usd["id"]]
    t = tres_compras
    assert _ids(client.get(BASE, params={"moneda": "ARS"}, headers=gestor)) == [t[k]["id"] for k in ("c", "b", "a")]
    assert client.get(BASE, params={"moneda": "EUR"}, headers=gestor).status_code == 422


def test_list_page_cost_does_not_grow_with_rows(client, gestor, tres_compras, query_counter):
    with query_counter() as uno:
        assert len(_ids(client.get(BASE, params={"q": "rebate"}, headers=gestor))) == 1
    with query_counter() as tres:
        assert len(_ids(client.get(BASE, params={"q": "bocas"}, headers=gestor))) == 3
    assert tres.total == uno.total


# ── Resumen ─────────────────────────────────────────────────────────


def _resumen(client, headers, **params) -> dict:
    resp = client.get(f"{BASE}/resumen", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_resumen_aggregates_every_matching_row(client, gestor, tres_compras):
    _crear_usd(client, gestor)
    data = _resumen(client, gestor)

    assert data["conteo"] == {"si": 3, "no": 1, "todas": 4}
    # a 1000 + b 1000 + c 1000 (voided, still matches `todas`) in ARS; the USD one apart.
    assert D(data["monto_total"]["ARS"]) == D("3000.00")
    assert D(data["monto_total"]["USD"]) == D("5.50")
    # a 10+10, b 5, c 4, usd 3
    assert data["unidades_total"] == 32


def test_resumen_is_not_paginated(client, gestor, tres_compras):
    data = _resumen(client, gestor, page_size=1)
    assert data["conteo"]["todas"] == 3


def test_resumen_aplica_narrows_totals_but_not_bucket_counts(client, gestor, tres_compras):
    si = _resumen(client, gestor, aplica="si")
    assert si["conteo"] == {"si": 2, "no": 1, "todas": 3}
    assert D(si["monto_total"]["ARS"]) == D("2000.00")
    assert si["unidades_total"] == 25

    no = _resumen(client, gestor, aplica="no")
    assert no["conteo"] == {"si": 2, "no": 1, "todas": 3}
    assert D(no["monto_total"]["ARS"]) == D("1000.00")
    assert no["unidades_total"] == 4


def test_resumen_honours_the_list_filters(client, gestor, tres_compras):
    _crear_usd(client, gestor)
    data = _resumen(client, gestor, marcas="Mercusys", fecha_desde="2026-09-15")
    assert data["conteo"] == {"si": 1, "no": 0, "todas": 1}
    assert D(data["monto_total"]["ARS"]) == D("1000.00")
    assert D(data["monto_total"]["USD"]) == D("0")
    assert data["unidades_total"] == 5

    usd = _resumen(client, gestor, moneda="USD", q="access")
    assert usd["conteo"] == {"si": 1, "no": 0, "todas": 1}
    assert usd["unidades_total"] == 3


def test_resumen_with_nothing_matching_is_all_zero(client, gestor, tres_compras):
    data = _resumen(client, gestor, q="nada que ver")
    assert data["conteo"] == {"si": 0, "no": 0, "todas": 0}
    assert D(data["monto_total"]["ARS"]) == D("0")
    assert D(data["monto_total"]["USD"]) == D("0")
    assert data["unidades_total"] == 0


@pytest.mark.parametrize(
    "params",
    [{"aplica": "quizas"}, {"moneda": "EUR"}, {"q": "x" * 201}],
    ids=["unknown-aplica", "unknown-moneda", "q-too-long"],
)
def test_resumen_rejects_invalid_filters(client, gestor, params):
    assert client.get(f"{BASE}/resumen", params=params, headers=gestor).status_code == 422


def test_resumen_accepts_a_q_of_exactly_200_chars(client, gestor):
    assert client.get(f"{BASE}/resumen", params={"q": "x" * 200}, headers=gestor).status_code == 200


def test_resumen_is_set_based(client, gestor, tres_compras, query_counter):
    with query_counter() as counter:
        _resumen(client, gestor)
    assert counter.matching("sell_in_compras") <= 2


# ── Detail ──────────────────────────────────────────────────────────


def test_get_returns_the_detail_with_consumption(client, gestor, productos):
    data = _crear(client, gestor)
    resp = client.get(f"{BASE}/{data['id']}", headers=gestor)

    assert resp.status_code == 200, resp.text
    detalle = resp.json()
    assert detalle["id"] == data["id"]
    assert detalle["unidades_consumidas"] == 0
    assert detalle["unidades_restantes"] == 20
    first = detalle["items"][0]
    assert first["codigo"] == "SW-8"
    assert D(first["descuento_unit"]) == D("25")
    assert D(first["costo_con_sell_in_unit"]) == D("75")


def test_get_unknown_is_404(client, gestor):
    assert client.get(f"{BASE}/424242", headers=gestor).status_code == 404


# ── Anular ──────────────────────────────────────────────────────────


def test_anular_once_then_409(client, gestor, productos, db):
    data = _crear(client, gestor)

    first = client.post(f"{BASE}/{data['id']}/anular", json={"motivo": "Cargada dos veces"}, headers=gestor)
    assert first.status_code == 200, first.text
    assert first.json()["estado"] == "anulada"
    assert db.get(SellInCompra, data["id"]).estado == "anulada"

    second = client.post(f"{BASE}/{data['id']}/anular", json={}, headers=gestor)
    assert second.status_code == 409
    assert _message(second)

    audit = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_COMPRA_ANULADA).all()
    assert sorted(r.item_id for r in audit) == [4512, 4513]
    assert {r.comentario for r in audit} == {"Cargada dos veces"}


def test_anular_without_body(client, gestor, productos):
    data = _crear(client, gestor)
    assert client.post(f"{BASE}/{data['id']}/anular", headers=gestor).status_code == 200


def test_anular_unknown_is_404(client, gestor):
    assert client.post(f"{BASE}/424242/anular", json={}, headers=gestor).status_code == 404


def test_anular_a_purchase_generated_by_a_brand_bonus_is_409(client, gestor, productos, admin_user, db):
    """Only the bonus (edit or void) changes what it generated; the worker would revive it anyway."""
    bono = SellInBonoMarca(
        marca="TP-LINK",
        monto_unit=D("2"),
        moneda="ARS",
        fecha_desde=date(2026, 10, 1),
        fecha_hasta=date(2026, 10, 31),
        usuario_id=admin_user.id,
    )
    db.add(bono)
    db.flush()
    data = _crear(client, gestor)
    compra = db.get(SellInCompra, data["id"])
    compra.origen, compra.bono_id = "bono_marca", bono.id
    db.flush()

    resp = client.post(f"{BASE}/{data['id']}/anular", json={}, headers=gestor)

    assert resp.status_code == 409
    assert "bono de marca" in _message(resp)
    db.expire_all()
    assert db.get(SellInCompra, data["id"]).estado == "activa"


# ── Anular masivo ───────────────────────────────────────────────────

MASIVO = f"{BASE}/anular-masivo"


def test_bulk_void_voids_every_purchase_with_the_single_void_audit(client, gestor, productos, db):
    a = _crear(client, gestor)
    b = _crear(client, gestor, lineas=[{"item_id": 4512, "cantidad": 4}])

    resp = client.post(MASIVO, json={"ids": [a["id"], b["id"]], "motivo": "Cargadas mal"}, headers=gestor)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"anuladas": [a["id"], b["id"]], "ya_anuladas": []}
    db.expire_all()
    assert {db.get(SellInCompra, x["id"]).estado for x in (a, b)} == {"anulada"}
    audit = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_COMPRA_ANULADA).all()
    assert sorted(r.item_id for r in audit) == [4512, 4512, 4513]  # one row per line, like the single void
    assert {r.comentario for r in audit} == {"Cargadas mal"}


def test_bulk_void_skips_and_reports_an_already_voided_purchase(client, gestor, productos, db):
    a, b = _crear(client, gestor), _crear(client, gestor)
    client.post(f"{BASE}/{a['id']}/anular", json={}, headers=gestor)

    resp = client.post(MASIVO, json={"ids": [a["id"], b["id"]]}, headers=gestor)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"anuladas": [b["id"]], "ya_anuladas": [a["id"]]}


def test_bulk_void_is_all_or_nothing_and_names_each_refused_purchase(client, gestor, productos, admin_user, db):
    bono = SellInBonoMarca(
        marca="TP-LINK",
        monto_unit=D("2"),
        moneda="ARS",
        fecha_desde=date(2026, 10, 1),
        fecha_hasta=date(2026, 10, 31),
        usuario_id=admin_user.id,
    )
    db.add(bono)
    db.flush()
    manual, generada = _crear(client, gestor), _crear(client, gestor)
    compra = db.get(SellInCompra, generada["id"])
    compra.origen, compra.bono_id = "bono_marca", bono.id
    db.flush()

    resp = client.post(MASIVO, json={"ids": [manual["id"], generada["id"], 424242]}, headers=gestor)

    assert resp.status_code == 409, resp.text
    detail = resp.json()  # a dict detail without "code" is the body root (app.core.exceptions)
    assert detail["mensaje"] == "No se anuló ninguna: 2 no se pueden anular"
    assert [r["id"] for r in detail["rechazadas"]] == [generada["id"], 424242]
    assert "bono de marca" in detail["rechazadas"][0]["motivo"]
    assert detail["rechazadas"][1]["motivo"] == "La compra 424242 no existe"
    db.expire_all()
    assert db.get(SellInCompra, manual["id"]).estado == "activa"  # voided first, rolled back with the rest
    assert db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_COMPRA_ANULADA).count() == 0


def test_bulk_void_releases_the_units_exactly_like_the_single_void(client, gestor, productos, db, monkeypatch):
    """The bulk action runs the single void per purchase: same recompute and FIFO calls, in the same order."""
    llamadas = []

    class Costing:
        def recompute(self, _db, item_ids, isolate_failures):
            llamadas.append(("recompute", sorted(item_ids), isolate_failures))

    monkeypatch.setattr(compras_service, "get_costing", lambda: Costing())
    monkeypatch.setattr(
        compras_service.bonos_costo, "seguir_fifo", lambda _db, ids: llamadas.append(("fifo", sorted(ids)))
    )
    a = _crear(client, gestor)
    b = _crear(client, gestor, lineas=[{"item_id": 4513, "cantidad": 2}])
    llamadas.clear()
    client.post(f"{BASE}/{a['id']}/anular", json={}, headers=gestor)
    client.post(f"{BASE}/{b['id']}/anular", json={}, headers=gestor)
    individual = list(llamadas)
    a2 = _crear(client, gestor)
    b2 = _crear(client, gestor, lineas=[{"item_id": 4513, "cantidad": 2}])
    llamadas.clear()

    assert client.post(MASIVO, json={"ids": [a2["id"], b2["id"]]}, headers=gestor).status_code == 200

    assert llamadas == individual


@pytest.mark.parametrize("ids", [[], list(range(1, 502))])
def test_bulk_void_needs_between_1_and_500_ids(client, gestor, ids):
    assert client.post(MASIVO, json={"ids": ids}, headers=gestor).status_code == 422
