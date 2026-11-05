"""The cost mode the panel's selector opens preselected with: a global setting (`configuracion` key
`sell_in_modo_por_defecto`) that anyone who sees the panel reads and only an admin changes. It never changes costing:
a product without a mode row stays FIFO in the engine."""

from __future__ import annotations

import pytest

from app.models.configuracion import Configuracion

URL = "/api/sell-in/productos/modo-por-defecto"
CLAVE = "sell_in_modo_por_defecto"


@pytest.fixture()
def ven_panel(rol_admin, rol_ventas, grant_permiso) -> None:
    for rol in (rol_admin, rol_ventas):
        grant_permiso(rol, "productos.ver")
        grant_permiso(rol, "sell_in.ver")


def test_without_a_setting_it_is_fifo(client, ven_panel, auth_headers) -> None:
    resp = client.get(URL, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"modo": "fifo"}


def test_reading_needs_the_panel_permissions(client, rol_ventas, grant_permiso, auth_headers) -> None:
    grant_permiso(rol_ventas, "productos.ver")
    assert client.get(URL, headers=auth_headers).status_code == 403


def test_an_admin_sets_it_and_everyone_reads_it(client, db, ven_panel, admin_auth_headers, auth_headers) -> None:
    resp = client.put(URL, json={"modo": "ponderado"}, headers=admin_auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"modo": "ponderado"}
    assert db.query(Configuracion).filter(Configuracion.clave == CLAVE).one().valor == "ponderado"
    assert client.get(URL, headers=auth_headers).json() == {"modo": "ponderado"}

    assert client.put(URL, json={"modo": "manual"}, headers=admin_auth_headers).json() == {"modo": "manual"}
    assert db.query(Configuracion).filter(Configuracion.clave == CLAVE).count() == 1


def test_a_non_admin_cannot_change_it(client, db, ven_panel, auth_headers) -> None:
    assert client.put(URL, json={"modo": "ponderado"}, headers=auth_headers).status_code == 403
    assert db.query(Configuracion).filter(Configuracion.clave == CLAVE).count() == 0


@pytest.mark.parametrize("body", [{"modo": "promedio"}, {}, {"modo": "fifo", "otro": 1}])
def test_an_unknown_mode_is_refused(client, db, ven_panel, admin_auth_headers, body) -> None:
    assert client.put(URL, json=body, headers=admin_auth_headers).status_code == 422
    assert db.query(Configuracion).filter(Configuracion.clave == CLAVE).count() == 0


def test_a_broken_stored_value_reads_as_fifo(client, db, ven_panel, auth_headers) -> None:
    db.add(Configuracion(clave=CLAVE, valor="cualquiera", tipo="string"))
    db.commit()
    assert client.get(URL, headers=auth_headers).json() == {"modo": "fifo"}


def test_the_product_mode_routes_still_answer(client, ven_panel, auth_headers) -> None:
    # A product id still routes to its own modes, not to the setting.
    resp = client.get("/api/sell-in/productos/999999/modos", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["item_id"] == 999999
