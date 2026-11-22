# ruff: noqa: F811 - the fixtures imported from the neighbour test module are taken as parameters
"""A brand bonus loaded on its own (tacticals approval S6): `POST /api/sell-in/bonos` stores it `pendiente`,
`POST /api/sell-in/bonos/{id}/aprobar` approves it with `tacticals.aprobar` only, and a money edit of an approved one
sends it back (S4/S5) while a description edit does not. A tactical's bonus is approved with its tactical. SQLite."""

from __future__ import annotations

import pytest

from app.models.sell_in import SellInBonoMarca
from tests.routers.test_sell_in_bonos import BASE, _body, _crear, _message, gestor, productos  # noqa: F401

APROBAR = "tacticals.aprobar"


@pytest.fixture()
def aprobador(rol_admin, grant_permiso, gestor):
    grant_permiso(rol_admin, APROBAR)
    return gestor


def test_a_new_bonus_is_pending(client, gestor, productos) -> None:
    assert _crear(client, gestor)["estado"] == "pendiente"
    pendientes = client.get(BASE, params={"estado": "pendiente"}, headers=gestor).json()
    assert pendientes["total"] == 1


def test_approving_needs_the_permission_and_happens_once(client, gestor, productos, rol_admin, grant_permiso) -> None:
    bono = _crear(client, gestor)
    assert client.post(f"{BASE}/{bono['id']}/aprobar", headers=gestor).status_code == 403

    grant_permiso(rol_admin, APROBAR)
    resp = client.post(f"{BASE}/{bono['id']}/aprobar", headers=gestor)

    assert (resp.status_code, resp.json()["estado"]) == (200, "activa")
    segunda = client.post(f"{BASE}/{bono['id']}/aprobar", headers=gestor)
    assert segunda.status_code == 409
    assert "ya está aprobado" in _message(segunda)
    assert client.post(f"{BASE}/999999/aprobar", headers=gestor).status_code == 404


def test_a_voided_bonus_or_a_tactical_s_line_is_a_409(client, db, aprobador, productos, admin_user) -> None:
    anulado = _crear(client, aprobador)
    client.post(f"{BASE}/{anulado['id']}/anular", headers=aprobador)
    assert client.post(f"{BASE}/{anulado['id']}/aprobar", headers=aprobador).status_code == 409

    linea = _crear(client, aprobador)
    bono = db.get(SellInBonoMarca, linea["id"])
    bono.tactical_id = _tactical_id(db, admin_user)
    bono.tactical_linea = 1
    db.commit()
    resp = client.post(f"{BASE}/{linea['id']}/aprobar", headers=aprobador)
    assert resp.status_code == 409
    assert "se aprueba desde el tactical" in _message(resp)


def _tactical_id(db, admin_user) -> int:
    from datetime import date

    from app.models.tactical import Tactical

    tactical = Tactical(tipo="sell_in", nombre="T", marca="TP-LINK", fecha_desde=date(2026, 10, 1),
                        fecha_hasta=date(2026, 12, 31), moneda="ARS", estado="pendiente",
                        usuario_id=admin_user.id)  # fmt: skip
    db.add(tactical)
    db.flush()
    return tactical.id


def test_a_money_edit_sends_an_approved_bonus_back_and_the_description_does_not(client, aprobador, productos) -> None:
    bono = _crear(client, aprobador)
    client.post(f"{BASE}/{bono['id']}/aprobar", headers=aprobador)

    texto = client.put(f"{BASE}/{bono['id']}", json=_body(descripcion="Otro texto"), headers=aprobador)
    assert (texto.status_code, texto.json()["estado"]) == (200, "activa")

    monto = client.put(
        f"{BASE}/{bono['id']}", json=_body(descripcion="Otro texto", monto_unit="3.00"), headers=aprobador
    )
    assert (monto.status_code, monto.json()["estado"]) == (200, "pendiente")


def test_an_edit_of_a_pending_bonus_keeps_it_pending(client, gestor, productos) -> None:
    bono = _crear(client, gestor)

    resp = client.put(f"{BASE}/{bono['id']}", json=_body(monto_unit="3.00"), headers=gestor)

    assert (resp.status_code, resp.json()["estado"]) == (200, "pendiente")
