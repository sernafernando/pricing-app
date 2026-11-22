# ruff: noqa: F811 - the fixtures imported from the neighbour test module are taken as parameters
"""`POST /api/tacticals/{id}/aprobar` (tacticals approval S3): only with `tacticals.aprobar`, which is opt-in (a
SUPERADMIN without the per-user override is refused, L31: "lo más probable es que el permiso se lo de a alejandro
solo"); its author may approve; a new tactical reads `pendiente`; the pending filter. SQLite test database; the
engines' rules on Postgres (`tests/services/test_tacticals_aprobacion_postgres.py`)."""

from __future__ import annotations

import pytest

from app.models.permiso import Permiso, UsuarioPermisoOverride
from tests.conftest import make_access_token
from tests.routers.test_tacticals import BASE, _body, _message, productos, sell_out  # noqa: F401 - fixtures

APROBAR = "tacticals.aprobar"


@pytest.fixture()
def aprobador(rol_admin, grant_permiso, sell_out):
    grant_permiso(rol_admin, APROBAR)
    return sell_out


def _crear(client, headers) -> dict:
    resp = client.post(BASE, json=_body(), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_new_tactical_reads_pending_with_no_approver(client, productos, sell_out) -> None:
    creado = _crear(client, sell_out)

    assert (creado["estado"], creado["aprobado_por"], creado["aprobado_at"]) == ("pendiente", None, None)
    assert creado["lineas"][0]["estado"] == "pendiente"
    pendientes = client.get(BASE, params={"estado": "pendientes_aprobacion"}, headers=sell_out).json()
    assert [t["id"] for t in pendientes["items"]] == [creado["id"]]
    assert client.get(BASE, params={"estado": "vigentes"}, headers=sell_out).json()["total"] == 0


def test_without_the_permission_it_is_a_403_and_nothing_changes(client, productos, sell_out) -> None:
    creado = _crear(client, sell_out)

    resp = client.post(f"{BASE}/{creado['id']}/aprobar", headers=sell_out)

    assert resp.status_code == 403
    assert client.get(f"{BASE}/{creado['id']}", headers=sell_out).json()["estado"] == "pendiente"


def test_its_author_approves_it_with_the_permission(client, productos, aprobador, admin_user) -> None:
    creado = _crear(client, aprobador)

    resp = client.post(f"{BASE}/{creado['id']}/aprobar", headers=aprobador)

    assert resp.status_code == 200, resp.text
    aprobado = resp.json()
    assert (aprobado["estado"], aprobado["aprobado_por"], aprobado["aprobado_por_nombre"]) == (
        "activo", admin_user.id, admin_user.nombre,
    )  # fmt: skip
    assert aprobado["aprobado_at"] is not None
    assert aprobado["lineas"][0]["estado"] == "activa"
    segunda = client.post(f"{BASE}/{creado['id']}/aprobar", headers=aprobador)
    assert segunda.status_code == 409
    assert "ya está aprobado" in _message(segunda)
    assert client.post(f"{BASE}/999999/aprobar", headers=aprobador).status_code == 404


def test_a_voided_tactical_is_a_409(client, productos, aprobador) -> None:
    creado = _crear(client, aprobador)
    client.post(f"{BASE}/{creado['id']}/anular", headers=aprobador)

    assert client.post(f"{BASE}/{creado['id']}/aprobar", headers=aprobador).status_code == 409


def test_a_superadmin_needs_the_per_user_override(client, db, productos, sell_out, rma_superadmin_user) -> None:
    creado = _crear(client, sell_out)
    headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}

    assert client.post(f"{BASE}/{creado['id']}/aprobar", headers=headers).status_code == 403

    permiso = Permiso(codigo=APROBAR, nombre=APROBAR, descripcion="", categoria="tacticals", orden=999)
    db.add(permiso)
    db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=rma_superadmin_user.id, permiso_id=permiso.id, concedido=True))
    db.commit()
    assert client.post(f"{BASE}/{creado['id']}/aprobar", headers=headers).status_code == 200


def test_a_money_edit_through_the_api_sends_it_back_and_the_name_does_not(client, productos, aprobador) -> None:
    creado = _crear(client, aprobador)
    client.post(f"{BASE}/{creado['id']}/aprobar", headers=aprobador)

    renombrado = client.patch(f"{BASE}/{creado['id']}", json={"nombre": "Otro nombre"}, headers=aprobador)
    assert (renombrado.status_code, renombrado.json()["estado"]) == (200, "activo")

    cambio = client.put(
        f"{BASE}/{creado['id']}",
        json=_body(lineas=[{"alcance": "productos", "item_ids": [4512], "modo_monto": "por_unidad", "valor": "12",
                            "tope_unidades": 50}]),
        headers=aprobador,
    )  # fmt: skip
    assert cambio.status_code == 200, cambio.text
    assert (cambio.json()["estado"], cambio.json()["aprobado_por"]) == ("pendiente", None)
