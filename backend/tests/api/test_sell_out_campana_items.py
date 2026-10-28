"""Sell-out campaigns API with per-product amounts (sell-in-sell-out T22b S25: legacy grouped offsets), on the
SQLite test database like `tests/routers/test_sell_out_campanas.py`; the stored values are proven on Postgres by
`tests/services/sell_out/test_campanas_postgres.py`."""

from __future__ import annotations

import pytest

from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.producto import ProductoERP

BASE = "/api/sell-out/campanas"
ROUTER, AJENO = 2964, 950


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_out.ver")
    grant_permiso(rol_admin, "sell_out.gestionar")
    return admin_auth_headers


@pytest.fixture()
def grupo(db) -> int:
    db.add_all(ProductoERP(item_id=i, codigo=f"C{i}", descripcion="P") for i in (ROUTER, AJENO))
    grupo = OffsetGrupo(nombre="TP-Link routers")
    db.add(grupo)
    db.flush()
    db.add(OffsetGrupoFiltro(grupo_id=grupo.id, item_id=ROUTER))
    db.flush()
    return grupo.id


def _body(grupo: int, **overrides) -> dict:
    body = {
        "nombre": "Agrupada",
        "fecha_desde": "2026-11-01",
        "fecha_hasta": "2026-11-30",
        "tipo": "por_unidad",
        "monto_unit": "10.00",
        "grupo_ids": [grupo],
    }
    body.update(overrides)
    return body


def test_create_edit_and_read_return_the_product_amounts(client, gestor, grupo) -> None:
    resp = client.post(BASE, json=_body(grupo, items=[{"item_id": ROUTER, "monto_unit": "25"}]), headers=gestor)
    assert resp.status_code == 201, resp.text
    campana_id = resp.json()["id"]
    assert [(i["item_id"], float(i["monto_unit"])) for i in resp.json()["items"]] == [(ROUTER, 25.0)]

    resp = client.put(f"{BASE}/{campana_id}", json=_body(grupo, items=[]), headers=gestor)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []

    listado = client.get(BASE, headers=gestor).json()["items"]
    assert [c["items"] for c in listado] == [[]]


def test_a_product_outside_the_campaign_groups_is_a_422_naming_it(client, gestor, grupo) -> None:
    resp = client.post(BASE, json=_body(grupo, items=[{"item_id": AJENO, "monto_unit": "5"}]), headers=gestor)
    assert resp.status_code == 422
    assert f"El producto {AJENO} no está en los grupos de la campaña" in resp.text
    assert client.get(BASE, headers=gestor).json()["total"] == 0


def test_product_amounts_on_a_percentage_campaign_are_a_422(client, gestor, grupo) -> None:
    body = _body(
        grupo, tipo="porcentaje", monto_unit=None, porcentaje="2", items=[{"item_id": ROUTER, "monto_unit": "5"}]
    )
    resp = client.post(BASE, json=body, headers=gestor)
    assert resp.status_code == 422
    assert "Una campaña por porcentaje no lleva montos por producto" in resp.text


def _creada_con_monto(client, gestor, grupo) -> int:
    resp = client.post(BASE, json=_body(grupo, items=[{"item_id": ROUTER, "monto_unit": "25"}]), headers=gestor)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _montos(resp) -> list:
    return [(i["item_id"], float(i["monto_unit"])) for i in resp.json()["items"]]


def test_an_edit_without_items_keeps_the_stored_amounts(client, gestor, grupo) -> None:
    # A client that does not know about items (e.g. renaming the campaign) must not wipe them.
    campana_id = _creada_con_monto(client, gestor, grupo)

    resp = client.put(f"{BASE}/{campana_id}", json=_body(grupo, nombre="Renombrada"), headers=gestor)

    assert resp.status_code == 200, resp.text
    assert (resp.json()["nombre"], _montos(resp)) == ("Renombrada", [(ROUTER, 25.0)])
    assert _montos(client.get(f"{BASE}/{campana_id}", headers=gestor)) == [(ROUTER, 25.0)]


def test_an_edit_with_an_empty_list_clears_the_amounts(client, gestor, grupo) -> None:
    campana_id = _creada_con_monto(client, gestor, grupo)

    resp = client.put(f"{BASE}/{campana_id}", json=_body(grupo, items=[]), headers=gestor)

    assert resp.status_code == 200, resp.text
    assert _montos(resp) == []


def test_an_edit_with_a_list_replaces_the_amounts(client, gestor, grupo) -> None:
    campana_id = _creada_con_monto(client, gestor, grupo)

    resp = client.put(
        f"{BASE}/{campana_id}", json=_body(grupo, items=[{"item_id": ROUTER, "monto_unit": "30"}]), headers=gestor
    )

    assert resp.status_code == 200, resp.text
    assert _montos(resp) == [(ROUTER, 30.0)]


def test_switching_to_percentage_without_clearing_the_amounts_is_a_422(client, gestor, grupo) -> None:
    campana_id = _creada_con_monto(client, gestor, grupo)

    body = _body(grupo, tipo="porcentaje", monto_unit=None, porcentaje="2")
    resp = client.put(f"{BASE}/{campana_id}", json=body, headers=gestor)

    assert resp.status_code == 422
    assert "Una campaña por porcentaje no lleva montos por producto" in resp.text
    assert _montos(client.get(f"{BASE}/{campana_id}", headers=gestor)) == [(ROUTER, 25.0)]


def test_each_product_amount_comes_with_the_product_code_and_description(client, gestor, grupo) -> None:
    # The panel shows which product each stored amount is for, not a bare id.
    resp = client.post(BASE, json=_body(grupo, items=[{"item_id": ROUTER, "monto_unit": "25"}]), headers=gestor)
    assert resp.status_code == 201, resp.text

    [item] = client.get(BASE, headers=gestor).json()["items"][0]["items"]
    assert (item["item_id"], item["codigo"], item["descripcion"]) == (ROUTER, f"C{ROUTER}", "P")
