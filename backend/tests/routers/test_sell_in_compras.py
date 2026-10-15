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
from app.models.sell_in import SellInCompra, SellInCompraItem, SellInConsumo
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
            item_id=4512, codigo="SW-8", descripcion="Switch 8 bocas", costo=100.0, moneda_costo=TipoMoneda.ARS
        ),
        ProductoERP(
            item_id=4513, codigo="SW-16", descripcion="Switch 16 bocas", costo=300.0, moneda_costo=TipoMoneda.ARS
        ),
        ProductoERP(item_id=4514, codigo="AP-1", descripcion="Access point", costo=10.0, moneda_costo=TipoMoneda.USD),
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
    ("get", f"{BASE}/1", None),
    ("post", f"{BASE}/1/anular", {}),
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
    assert (compra.proveedor_id, compra.pedido_compra_id) == (proveedor.id, pedido.id)


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
    c = _crear(client, gestor, fecha_compra="2026-10-10", lineas=[{"item_id": 4512, "cantidad": 4}])
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
