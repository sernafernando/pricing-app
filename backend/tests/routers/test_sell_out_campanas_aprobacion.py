# ruff: noqa: F811 - the fixtures imported from the neighbour test module are taken as parameters
"""A campaign loaded on its own (tacticals approval S6): `POST /api/sell-out/campanas` stores it `pendiente`,
`POST /api/sell-out/campanas/{id}/aprobar` approves it with `tacticals.aprobar` only, and a money edit of an approved
one sends it back (S4/S5) while a name edit does not. SQLite."""

from __future__ import annotations

import pytest

from tests.routers.test_sell_out_campanas import BASE, _body, _crear, _message, gestor, grupos  # noqa: F401

APROBAR = "tacticals.aprobar"


@pytest.fixture()
def aprobador(rol_admin, grant_permiso, gestor):
    grant_permiso(rol_admin, APROBAR)
    return gestor


def _ids(grupos) -> list[int]:
    return [g.id if hasattr(g, "id") else g for g in grupos]


def test_a_new_campaign_is_pending(client, gestor, grupos) -> None:
    assert _crear(client, gestor, _ids(grupos))["estado"] == "pendiente"
    assert client.get(BASE, params={"estado": "pendiente"}, headers=gestor).json()["total"] == 1


def test_approving_needs_the_permission_and_happens_once(client, gestor, grupos, rol_admin, grant_permiso) -> None:
    campana = _crear(client, gestor, _ids(grupos))
    assert client.post(f"{BASE}/{campana['id']}/aprobar", headers=gestor).status_code == 403

    grant_permiso(rol_admin, APROBAR)
    resp = client.post(f"{BASE}/{campana['id']}/aprobar", headers=gestor)

    assert (resp.status_code, resp.json()["estado"]) == (200, "activa")
    segunda = client.post(f"{BASE}/{campana['id']}/aprobar", headers=gestor)
    assert segunda.status_code == 409
    assert "ya está aprobada" in _message(segunda)
    assert client.post(f"{BASE}/999999/aprobar", headers=gestor).status_code == 404


def test_a_money_edit_sends_an_approved_campaign_back_and_the_name_does_not(client, aprobador, grupos) -> None:
    ids = _ids(grupos)
    campana = _crear(client, aprobador, ids)
    client.post(f"{BASE}/{campana['id']}/aprobar", headers=aprobador)

    nombre = client.put(f"{BASE}/{campana['id']}", json=_body(ids, nombre="Otro nombre"), headers=aprobador)
    assert (nombre.status_code, nombre.json()["estado"]) == (200, "activa")

    monto = client.put(f"{BASE}/{campana['id']}", json=_body(ids, nombre="Otro nombre", monto_unit="2000.00"),
                       headers=aprobador)  # fmt: skip
    assert (monto.status_code, monto.json()["estado"]) == (200, "pendiente")


def test_a_voided_campaign_is_a_409(client, aprobador, grupos) -> None:
    campana = _crear(client, aprobador, _ids(grupos))
    client.post(f"{BASE}/{campana['id']}/anular", headers=aprobador)

    assert client.post(f"{BASE}/{campana['id']}/aprobar", headers=aprobador).status_code == 409
