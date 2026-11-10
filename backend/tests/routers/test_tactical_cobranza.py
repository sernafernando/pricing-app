"""Router `/api/tacticals/{id}/cobranza` (tactical cobranza S2): save, edit and undo a tactical's collection record,
with the permission that edits the tactical (`<tipo>.gestionar`); the list carries the record, the filter and KPIs."""

from __future__ import annotations

import pytest

from app.models.producto import ProductoERP
from tests.routers.test_tacticals import BASE, _body


@pytest.fixture()
def productos(db):
    db.add(ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", categoria="Switches"))
    db.flush()


@pytest.fixture()
def lector(rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_out.ver")
    return admin_auth_headers


@pytest.fixture()
def tactical_id(client, productos, rol_admin, admin_auth_headers, grant_permiso) -> int:
    grant_permiso(rol_admin, "sell_out.gestionar")
    resp = client.post(BASE, json=_body(), headers=admin_auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


COBRO = {"fecha_cobro": "2026-11-09", "medio": "fondo_distribuidor", "distribuidor": "Grupo Núcleo",
         "observaciones": "Fondo de noviembre"}  # fmt: skip


def test_save_edit_list_and_undo(client, tactical_id, lector) -> None:
    resp = client.put(f"{BASE}/{tactical_id}/cobranza", json=COBRO, headers=lector)
    assert resp.status_code == 200, resp.text
    cobranza = resp.json()["cobranza"]
    assert {k: cobranza[k] for k in ("fecha_cobro", "medio", "nc_numero", "distribuidor", "observaciones")} == {
        "fecha_cobro": "2026-11-09",
        "medio": "fondo_distribuidor",
        "nc_numero": None,
        "distribuidor": "Grupo Núcleo",
        "observaciones": "Fondo de noviembre",
    }

    editado = client.put(f"{BASE}/{tactical_id}/cobranza", json={"fecha_cobro": "2026-11-10"}, headers=lector)
    assert (editado.json()["cobranza"]["fecha_cobro"], editado.json()["cobranza"]["medio"]) == ("2026-11-10", None)

    listado = client.get(BASE, params={"cobranza": "cobrados", "estado": "vigentes"}, headers=lector).json()
    assert [t["id"] for t in listado["items"]] == [tactical_id]
    assert listado["items"][0]["cobranza"]["fecha_cobro"] == "2026-11-10"
    assert (listado["kpis"]["cobrados"]["cantidad"], listado["kpis"]["pendientes"]["cantidad"]) == (1, 0)
    assert client.get(BASE, params={"cobranza": "pendientes"}, headers=lector).json()["total"] == 0

    deshecho = client.delete(f"{BASE}/{tactical_id}/cobranza", headers=lector)
    assert deshecho.status_code == 200, deshecho.text
    assert deshecho.json()["cobranza"] is None
    assert client.delete(f"{BASE}/{tactical_id}/cobranza", headers=lector).status_code == 404


def test_the_date_is_required(client, tactical_id, lector) -> None:
    resp = client.put(
        f"{BASE}/{tactical_id}/cobranza", json={"medio": "otro", "otro_detalle": "Cheque"}, headers=lector
    )

    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("cuerpo", "mensaje"),
    [
        ({"medio": "otro", "nc_numero": "NC 1"}, "El número de NC va solo con el medio Nota de crédito"),
        ({"distribuidor": "Grupo Núcleo"}, "El distribuidor va solo con el medio Fondo en distribuidor"),
        ({"medio": "nota_credito", "otro_detalle": "x"}, "El detalle va solo con el medio Otro"),
    ],
)
def test_a_detail_of_another_medium_is_a_422(client, tactical_id, lector, cuerpo, mensaje) -> None:
    resp = client.put(f"{BASE}/{tactical_id}/cobranza", json={"fecha_cobro": "2026-11-09", **cuerpo}, headers=lector)

    assert resp.status_code == 422
    assert mensaje in str(resp.json())


def test_an_unknown_medium_and_long_texts_are_422(client, tactical_id, lector) -> None:
    url = f"{BASE}/{tactical_id}/cobranza"
    assert client.put(url, json={"fecha_cobro": "2026-11-09", "medio": "cheque"}, headers=lector).status_code == 422
    largo = {"fecha_cobro": "2026-11-09", "observaciones": "x" * 2001}
    assert client.put(url, json=largo, headers=lector).status_code == 422
    assert client.get(BASE, params={"cobranza": "todos"}, headers=lector).status_code == 422


def test_saving_and_undoing_need_the_edit_permission(client, tactical_id, lector, rol_admin, db) -> None:
    from app.models.permiso import Permiso, RolPermisoBase

    gestionar = db.query(Permiso).filter(Permiso.codigo == "sell_out.gestionar").one()
    db.query(RolPermisoBase).filter(RolPermisoBase.rol_id == rol_admin.id,
                                    RolPermisoBase.permiso_id == gestionar.id).delete()  # fmt: skip
    db.commit()

    assert client.put(f"{BASE}/{tactical_id}/cobranza", json=COBRO, headers=lector).status_code == 403
    assert client.delete(f"{BASE}/{tactical_id}/cobranza", headers=lector).status_code == 403
    assert client.put(f"{BASE}/999/cobranza", json=COBRO, headers=lector).status_code == 404
    assert client.get(BASE, headers=lector).status_code == 200  # reading stays with `sell_out.ver`
