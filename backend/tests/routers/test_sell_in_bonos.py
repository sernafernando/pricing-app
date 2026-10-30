"""Router: brand bonuses (`/api/sell-in/bonos`), sell-in-sell-out T3c-3.

A bonus pays an amount per invoiced unit of a brand over a supplier-invoice
date range; the `sell_in.bono` worker applies it (tested in
`tests/services/sell_in/test_bonos_postgres.py`). This API only loads, lists,
edits and voids it, with the sell-in permissions and audit style.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.models.auditoria import Auditoria, TipoAccion
from app.models.producto import ProductoERP, TipoMoneda
from app.models.sell_in import SellInBonoMarca, SellInCompra, SellInCompraItem

BASE = "/api/sell-in/bonos"
VER = "sell_in.ver"
GESTIONAR = "sell_in.gestionar"


def _message(resp) -> str:
    message = resp.json()["error"]["message"]
    assert isinstance(message, str) and message
    return message


@pytest.fixture()
def productos(db):
    rows = [
        ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", costo=10.0),
        ProductoERP(item_id=4513, codigo="SW-16", descripcion="Switch", marca="MERCUSYS", costo=30.0),
    ]
    for row in rows:
        row.moneda_costo = TipoMoneda.USD
    db.add_all(rows)
    db.flush()
    return rows


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VER)
    grant_permiso(rol_admin, GESTIONAR)
    return admin_auth_headers


@pytest.fixture()
def lector(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VER)
    return admin_auth_headers


def _body(**overrides) -> dict:
    body = {
        "marca": "TP-LINK",
        "monto_unit": "2.50",
        "moneda": "USD",
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-12-31",
        "descripcion": "Acuerdo Q4 TP-Link",
    }
    body.update(overrides)
    return body


def _crear(client, headers, **overrides) -> dict:
    resp = client.post(BASE, json=_body(**overrides), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


ENDPOINTS = [
    ("post", BASE, _body()),
    ("get", BASE, None),
    ("get", f"{BASE}/1", None),
    ("put", f"{BASE}/1", _body()),
    ("post", f"{BASE}/1/anular", {}),
    ("post", f"{BASE}/anular-masivo", {"ids": [1]}),
]


@pytest.mark.parametrize("method,url,body", ENDPOINTS)
def test_every_endpoint_requires_a_permission(client, auth_headers, productos, method, url, body):
    kwargs = {"headers": auth_headers} | ({"json": body} if body is not None else {})
    assert getattr(client, method)(url, **kwargs).status_code == 403


@pytest.mark.parametrize("method,url,body", ENDPOINTS)
def test_every_endpoint_requires_authentication(client, productos, method, url, body):
    resp = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
    assert resp.status_code in (401, 403)


@pytest.mark.parametrize("method,url,body", [e for e in ENDPOINTS if e[0] != "get"])
def test_writes_need_gestionar_not_just_ver(client, lector, productos, method, url, body):
    assert getattr(client, method)(url, json=body, headers=lector).status_code == 403


def test_ver_is_enough_to_read(client, lector):
    assert client.get(BASE, headers=lector).status_code == 200


def test_create_stores_the_bonus_with_the_author_from_the_token(client, gestor, productos, admin_user, db):
    data = _crear(client, gestor, usuario_id=999)

    assert {k: data[k] for k in ("marca", "monto_unit", "moneda", "fecha_desde", "fecha_hasta", "estado")} == {
        "marca": "TP-LINK",
        "monto_unit": "2.50",
        "moneda": "USD",
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-12-31",
        "estado": "activa",
    }
    assert data["usuario_id"] == admin_user.id
    assert (data["compras_activas"], data["unidades"]) == (0, 0)
    bono = db.get(SellInBonoMarca, data["id"])
    assert (bono.marca, bono.monto_unit, bono.usuario_id) == ("TP-LINK", Decimal("2.50"), admin_user.id)


def test_create_trims_the_brand(client, gestor, productos):
    assert _crear(client, gestor, marca="  TP-LINK ")["marca"] == "TP-LINK"


def test_create_writes_one_audit_row(client, gestor, productos, db):
    data = _crear(client, gestor)

    [row] = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_CREADO).all()
    assert row.item_id is None
    assert row.valores_anteriores is None
    assert row.valores_nuevos["bono_id"] == data["id"]
    assert row.valores_nuevos["monto_unit"] == "2.50"


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"marca": "NO-EXISTE"}, "marca"),
        ({"marca": "   "}, "marca"),
        ({"fecha_desde": "2027-01-01"}, "fecha"),
        ({"monto_unit": "0"}, "monto"),
        ({"monto_unit": "-1.00"}, "monto"),
    ],
)
def test_domain_errors_are_422_with_a_spanish_message(client, gestor, productos, db, overrides, fragment):
    resp = client.post(BASE, json=_body(**overrides), headers=gestor)

    assert resp.status_code == 422
    assert fragment in _message(resp).lower()
    assert db.query(SellInBonoMarca).count() == 0


@pytest.mark.parametrize("overrides", [{"moneda": "EUR"}, {"monto_unit": "1.005"}, {"marca": "X" * 101}])
def test_shape_errors_are_422(client, gestor, productos, overrides):
    assert client.post(BASE, json=_body(**overrides), headers=gestor).status_code == 422


def test_list_filters_by_estado_and_brand_newest_first(client, gestor, productos):
    viejo = _crear(client, gestor)
    otra = _crear(client, gestor, marca="MERCUSYS")
    anulado = _crear(client, gestor)
    client.post(f"{BASE}/{anulado['id']}/anular", json={}, headers=gestor)

    todos = client.get(BASE, headers=gestor).json()
    activos_tp = client.get(BASE, params={"estado": "activa", "marca": "TP-LINK"}, headers=gestor).json()

    assert [b["id"] for b in todos["items"]] == [anulado["id"], otra["id"], viejo["id"]]
    assert todos["total"] == 3
    assert [b["id"] for b in activos_tp["items"]] == [viejo["id"]]


def test_list_is_paginated(client, gestor, productos):
    ids = [_crear(client, gestor)["id"] for _ in range(3)]

    page = client.get(BASE, params={"page": 2, "page_size": 2}, headers=gestor).json()

    assert [b["id"] for b in page["items"]] == [ids[0]]
    assert (page["total"], page["page"], page["page_size"]) == (3, 2, 2)


def test_get_reports_what_the_bonus_generated(client, gestor, productos, admin_user, db):
    data = _crear(client, gestor)
    for estado, cantidad in (("activa", 4), ("activa", 6), ("anulada", 100)):
        compra = SellInCompra(
            fecha_compra=date(2026, 10, 10),
            moneda="USD",
            monto_total=Decimal(cantidad) * Decimal("2.50"),
            tipo_cambio=Decimal("1450"),
            formula="por_unidad",
            estado=estado,
            usuario_id=admin_user.id,
            origen="bono_marca",
            bono_id=data["id"],
        )
        db.add(compra)
        db.flush()
        db.add(
            SellInCompraItem(
                compra_id=compra.id,
                item_id=4512,
                cantidad=cantidad,
                costo_base_unit=Decimal("10"),
                monto_asignado=compra.monto_total,
            )
        )
    db.flush()

    resp = client.get(f"{BASE}/{data['id']}", headers=gestor)

    assert resp.status_code == 200
    assert {k: resp.json()[k] for k in ("compras_activas", "unidades", "monto_generado")} == {
        "compras_activas": 2,
        "unidades": 10,
        "monto_generado": "25.00",
    }


def test_get_unknown_is_404(client, gestor):
    resp = client.get(f"{BASE}/424242", headers=gestor)
    assert resp.status_code == 404
    assert "424242" in _message(resp)


def test_edit_replaces_the_bonus_and_audits_before_and_after(client, gestor, productos, db):
    data = _crear(client, gestor)

    resp = client.put(
        f"{BASE}/{data['id']}",
        json=_body(marca="MERCUSYS", monto_unit="3.00", moneda="ARS", fecha_hasta="2026-11-30", descripcion=None),
        headers=gestor,
    )

    assert resp.status_code == 200, resp.text
    assert {k: resp.json()[k] for k in ("marca", "monto_unit", "moneda", "fecha_hasta", "descripcion")} == {
        "marca": "MERCUSYS",
        "monto_unit": "3.00",
        "moneda": "ARS",
        "fecha_hasta": "2026-11-30",
        "descripcion": None,
    }
    [row] = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_EDITADO).all()
    assert (row.valores_anteriores["marca"], row.valores_nuevos["marca"]) == ("TP-LINK", "MERCUSYS")


def test_edit_validates_like_create(client, gestor, productos, db):
    data = _crear(client, gestor)

    resp = client.put(f"{BASE}/{data['id']}", json=_body(marca="MERCUSYS", fecha_hasta="2026-09-01"), headers=gestor)

    assert resp.status_code == 422
    assert "fecha" in _message(resp).lower()
    # A rejected edit leaves the bonus as it was and audits nothing.
    assert client.get(f"{BASE}/{data['id']}", headers=gestor).json() == data
    assert db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_EDITADO).count() == 0


def test_edit_of_a_voided_bonus_is_409_and_unknown_is_404(client, gestor, productos):
    data = _crear(client, gestor)
    client.post(f"{BASE}/{data['id']}/anular", json={}, headers=gestor)

    assert client.put(f"{BASE}/{data['id']}", json=_body(), headers=gestor).status_code == 409
    assert client.put(f"{BASE}/424242", json=_body(), headers=gestor).status_code == 404


def test_void_once_then_409_with_the_reason_audited(client, gestor, productos, db):
    data = _crear(client, gestor)

    first = client.post(f"{BASE}/{data['id']}/anular", json={"motivo": "La marca canceló el acuerdo"}, headers=gestor)
    second = client.post(f"{BASE}/{data['id']}/anular", headers=gestor)

    assert first.status_code == 200, first.text
    assert first.json()["estado"] == "anulada"
    assert second.status_code == 409
    assert "anulado" in _message(second)
    [row] = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_ANULADO).all()
    assert row.comentario == "La marca canceló el acuerdo"
    assert not row.es_masivo


def test_void_unknown_is_404(client, gestor):
    assert client.post(f"{BASE}/424242/anular", json={}, headers=gestor).status_code == 404


def test_the_purchases_api_tells_a_generated_purchase_from_a_manual_one(client, gestor, productos, admin_user, db):
    data = _crear(client, gestor)
    compra = SellInCompra(
        fecha_compra=date(2026, 10, 10),
        moneda="ARS",
        monto_total=Decimal("5"),
        formula="por_unidad",
        usuario_id=admin_user.id,
        origen="bono_marca",
        bono_id=data["id"],
    )
    db.add(compra)
    db.flush()

    resp = client.get(f"/api/sell-in/compras/{compra.id}", headers=gestor)

    assert resp.status_code == 200
    assert (resp.json()["origen"], resp.json()["bono_id"]) == ("bono_marca", data["id"])


# T27b (S36): `acumulable`, sell out's meaning; the reconcile reads it (tests/services/sell_in/test_bonos_acumulable).


def test_a_new_bonus_is_acumulable_unless_told_otherwise(client, gestor, productos, db):
    por_defecto = _crear(client, gestor)
    exclusivo = _crear(client, gestor, acumulable=False)

    assert (por_defecto["acumulable"], exclusivo["acumulable"]) == (True, False)
    assert db.get(SellInBonoMarca, exclusivo["id"]).acumulable is False
    rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_CREADO).all()
    assert sorted(r.valores_nuevos["acumulable"] for r in rows) == [False, True]


def test_editing_the_flag_stores_it_and_audits_before_and_after(client, gestor, productos, db):
    data = _crear(client, gestor)

    resp = client.put(f"{BASE}/{data['id']}", json=_body(acumulable=False), headers=gestor)

    assert resp.status_code == 200, resp.text
    assert resp.json()["acumulable"] is False
    assert db.get(SellInBonoMarca, data["id"]).acumulable is False
    [row] = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_EDITADO).all()
    assert (row.valores_anteriores["acumulable"], row.valores_nuevos["acumulable"]) == (True, False)


def test_an_edit_that_leaves_the_flag_out_keeps_the_stored_one(client, gestor, productos, db):
    data = _crear(client, gestor, acumulable=False)

    resp = client.put(f"{BASE}/{data['id']}", json=_body(monto_unit="3.00"), headers=gestor)

    assert resp.status_code == 200, resp.text
    assert (resp.json()["acumulable"], resp.json()["monto_unit"]) == (False, "3.00")
    assert client.get(BASE, headers=gestor).json()["items"][0]["acumulable"] is False


def test_the_flag_must_be_a_boolean(client, gestor, productos):
    resp = client.post(BASE, json=_body(acumulable="quizás"), headers=gestor)

    assert resp.status_code == 422


# ── Anular masivo ───────────────────────────────────────────────────

MASIVO = f"{BASE}/anular-masivo"


def test_bulk_void_voids_every_bonus_with_the_single_void_audit(client, gestor, productos, db):
    a, b = _crear(client, gestor), _crear(client, gestor, marca="MERCUSYS")

    resp = client.post(MASIVO, json={"ids": [a["id"], b["id"]], "motivo": "Acuerdo caído"}, headers=gestor)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"anuladas": [a["id"], b["id"]], "ya_anuladas": []}
    db.expire_all()
    assert {db.get(SellInBonoMarca, x["id"]).estado for x in (a, b)} == {"anulada"}
    rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_ANULADO).all()
    assert len(rows) == 2 and {r.comentario for r in rows} == {"Acuerdo caído"}
    assert {bool(r.es_masivo) for r in rows} == {True}


def test_bulk_void_skips_and_reports_an_already_voided_bonus(client, gestor, productos):
    a, b = _crear(client, gestor), _crear(client, gestor)
    client.post(f"{BASE}/{a['id']}/anular", json={}, headers=gestor)

    resp = client.post(MASIVO, json={"ids": [a["id"], b["id"]]}, headers=gestor)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"anuladas": [b["id"]], "ya_anuladas": [a["id"]]}


def test_bulk_void_of_bonuses_is_all_or_nothing(client, gestor, productos, db):
    a = _crear(client, gestor)

    resp = client.post(MASIVO, json={"ids": [a["id"], 424242]}, headers=gestor)

    assert resp.status_code == 409, resp.text
    assert resp.json() == {  # a dict detail without "code" is the body root (app.core.exceptions)
        "mensaje": "No se anuló ninguno: 1 no se puede anular",
        "rechazadas": [{"id": 424242, "motivo": "El bono 424242 no existe"}],
    }
    db.expire_all()
    assert db.get(SellInBonoMarca, a["id"]).estado == "activa"
    assert db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_ANULADO).count() == 0


def test_bulk_void_locks_every_bonus_in_id_order_before_voiding_any(client, gestor, productos, db):
    # Locking them as they came would let two bulk voids of the same bonuses in another order wait on each other.
    a, b = _crear(client, gestor), _crear(client, gestor)
    sentencias = []

    def _capturar(_conn, _cursor, statement, _parameters, _context, _many):
        if "FROM sell_in_bonos_marca" in statement:
            sentencias.append(statement)

    conn = db.connection()
    event.listen(conn, "before_cursor_execute", _capturar)
    try:
        resp = client.post(MASIVO, json={"ids": [b["id"], a["id"]]}, headers=gestor)
    finally:
        event.remove(conn, "before_cursor_execute", _capturar)

    assert resp.status_code == 200, resp.text
    assert "ORDER BY sell_in_bonos_marca.id" in sentencias[0] and " IN " in sentencias[0]
