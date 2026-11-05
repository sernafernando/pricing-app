"""Router `/api/tacticals` (tacticals T1): permissions by the tactical's kind, status codes and the contract's shape.
The engines' rules are proven on Postgres (`tests/services/test_tacticals_postgres.py`); SQLite test database."""

from __future__ import annotations

import pytest

from app.models.producto import ProductoERP

BASE = "/api/tacticals"


@pytest.fixture()
def productos(db):
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", categoria="Switches"))
    db.flush()


@pytest.fixture()
def sell_out(rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_out.ver")
    grant_permiso(rol_admin, "sell_out.gestionar")
    return admin_auth_headers


def _body(**overrides) -> dict:
    body = {
        "tipo": "sell_out",
        "nombre": "Tactical noviembre",
        "marca": "TP-LINK",
        "fecha_desde": "2026-11-01",
        "fecha_hasta": "2026-11-30",
        "moneda": "ARS",
        "lineas": [{"alcance": "productos", "item_ids": [4512], "modo_monto": "por_unidad", "valor": "10",
                    "tope_unidades": 50}],
    }  # fmt: skip
    body.update(overrides)
    return body


def _message(resp) -> str:
    return resp.json()["error"]["message"]


def test_create_read_and_void(client, productos, sell_out) -> None:
    resp = client.post(BASE, json=_body(), headers=sell_out)
    assert resp.status_code == 201, resp.text
    creado = resp.json()
    [linea] = creado["lineas"]
    assert (linea["linea"], linea["origen"], linea["tope_unidades"], linea["unidades_usadas"]) == (
        1, "sell_out_campana", 50, 0,
    )  # fmt: skip
    assert linea["productos"] == [{"item_id": 4512, "codigo": "SW-8", "descripcion": "Switch"}]

    assert client.get(f"{BASE}/{creado['id']}", headers=sell_out).json()["lineas"] == creado["lineas"]
    listado = client.get(BASE, params={"q": "noviembre"}, headers=sell_out).json()
    assert (listado["total"], [t["id"] for t in listado["items"]]) == (1, [creado["id"]])

    anulado = client.post(f"{BASE}/{creado['id']}/anular", json={"motivo": "Sin acuerdo"}, headers=sell_out)
    assert anulado.status_code == 200, anulado.text
    assert (anulado.json()["estado"], anulado.json()["lineas"][0]["estado"]) == ("anulado", "anulada")
    assert client.post(f"{BASE}/{creado['id']}/anular", headers=sell_out).status_code == 409


def test_a_broken_rule_is_a_422_naming_its_line(client, productos, sell_out) -> None:
    lineas = [{"alcance": "productos", "item_ids": [999], "modo_monto": "por_unidad", "valor": "10"}]

    resp = client.post(BASE, json=_body(lineas=lineas), headers=sell_out)

    assert resp.status_code == 422
    assert _message(resp) == "Línea 1: no existen los productos 999"


def test_permissions_follow_the_kind(client, productos, sell_out) -> None:
    assert client.post(BASE, json=_body(tipo="sell_in"), headers=sell_out).status_code == 403
    assert client.get(BASE, params={"tipo": "sell_in"}, headers=sell_out).status_code == 403
    assert client.get(BASE, headers=sell_out).status_code == 200  # only the readable kinds


def test_without_permissions_everything_is_403(client, productos, admin_auth_headers) -> None:
    assert client.post(BASE, json=_body(), headers=admin_auth_headers).status_code == 403
    assert client.get(BASE, headers=admin_auth_headers).status_code == 403


def test_unknown_is_404_and_an_inverted_period_is_422(client, sell_out) -> None:
    assert client.get(f"{BASE}/999", headers=sell_out).status_code == 404
    assert client.post(f"{BASE}/999/anular", headers=sell_out).status_code == 404
    resp = client.get(BASE, params={"desde": "2026-11-10", "hasta": "2026-11-01"}, headers=sell_out)
    assert resp.status_code == 422


def test_text_filters_are_bounded(client, sell_out) -> None:
    assert client.get(BASE, params={"q": "x" * 201}, headers=sell_out).status_code == 422
    assert client.get(BASE, params={"marca": "x" * 101}, headers=sell_out).status_code == 422


def test_the_note_is_bounded(client, productos, sell_out) -> None:
    assert client.post(BASE, json=_body(nota="x" * 2001), headers=sell_out).status_code == 422
