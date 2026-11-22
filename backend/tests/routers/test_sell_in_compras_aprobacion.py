# ruff: noqa: F811 - the fixtures imported from the neighbour test module are taken as parameters
"""A purchase loaded on its own (tacticals approval S6): `POST /api/sell-in/compras` stores it `pendiente`, and
`POST /api/sell-in/compras/{id}/aprobar` approves it with `tacticals.aprobar` only. A purchase has no edit. SQLite."""

from __future__ import annotations

import pytest

from tests.routers.test_sell_in_compras import BASE, _crear, _message, gestor, productos  # noqa: F401

APROBAR = "tacticals.aprobar"


@pytest.fixture()
def aprobador(rol_admin, grant_permiso, gestor):
    grant_permiso(rol_admin, APROBAR)
    return gestor


def test_a_new_purchase_is_pending(client, gestor, productos) -> None:
    compra = _crear(client, gestor)

    assert compra["estado"] == "pendiente"


def test_approving_needs_the_permission_and_happens_once(client, gestor, productos, rol_admin, grant_permiso) -> None:
    compra = _crear(client, gestor)
    assert client.post(f"{BASE}/{compra['id']}/aprobar", headers=gestor).status_code == 403

    grant_permiso(rol_admin, APROBAR)
    resp = client.post(f"{BASE}/{compra['id']}/aprobar", headers=gestor)

    assert (resp.status_code, resp.json()["estado"]) == (200, "activa")
    segunda = client.post(f"{BASE}/{compra['id']}/aprobar", headers=gestor)
    assert segunda.status_code == 409
    assert "ya está aprobada" in _message(segunda)
    assert client.post(f"{BASE}/999999/aprobar", headers=gestor).status_code == 404


def test_a_voided_purchase_is_a_409(client, aprobador, productos) -> None:
    compra = _crear(client, aprobador)
    client.post(f"{BASE}/{compra['id']}/anular", headers=aprobador)

    assert client.post(f"{BASE}/{compra['id']}/aprobar", headers=aprobador).status_code == 409
