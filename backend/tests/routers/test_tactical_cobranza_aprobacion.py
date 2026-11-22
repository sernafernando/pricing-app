# ruff: noqa: F811 - the fixtures imported from the neighbour test modules are taken as parameters
"""A tactical waiting for approval is not collected (tacticals approval S16, L10: "a tactical pending approval must not
offer 'Cargar cobro' (disabled with tooltip 'Se aprueba antes de cobrar'), backend refuses too"): saving its collection
is a 409 with that message and stores nothing, while an approved one saves and edits it as before. Undoing a collection
stays allowed on a pending tactical: one that went back to pending may hold the record it had while approved. SQLite."""

from __future__ import annotations

import pytest

from app.models.tactical import TacticalCobranza
from app.services import tacticals as service
from tests.routers.test_tactical_cobranza import COBRO
from tests.routers.test_tacticals import BASE, _body, _message, productos  # noqa: F401 - fixtures

APROBAR = "tacticals.aprobar"


@pytest.fixture()
def gestor(rol_admin, admin_auth_headers, grant_permiso):
    for codigo in ("sell_out.ver", "sell_out.gestionar", APROBAR):
        grant_permiso(rol_admin, codigo)
    return admin_auth_headers


def _crear(client, headers) -> int:
    resp = client.post(BASE, json=_body(), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _cobranzas(db, tactical_id: int) -> int:
    db.expire_all()
    return db.query(TacticalCobranza).filter(TacticalCobranza.tactical_id == tactical_id).count()


def test_saving_the_collection_of_a_pending_tactical_is_a_409_and_stores_nothing(client, db, productos, gestor) -> None:
    tactical_id = _crear(client, gestor)

    resp = client.put(f"{BASE}/{tactical_id}/cobranza", json=COBRO, headers=gestor)

    assert resp.status_code == 409
    assert _message(resp) == "Se aprueba antes de cobrar"
    assert _cobranzas(db, tactical_id) == 0
    assert client.get(f"{BASE}/{tactical_id}", headers=gestor).json()["cobranza"] is None


def test_an_approved_tactical_saves_and_edits_its_collection_as_before(client, productos, gestor) -> None:
    tactical_id = _crear(client, gestor)
    assert client.post(f"{BASE}/{tactical_id}/aprobar", headers=gestor).status_code == 200

    guardado = client.put(f"{BASE}/{tactical_id}/cobranza", json=COBRO, headers=gestor)
    editado = client.put(f"{BASE}/{tactical_id}/cobranza", json={"fecha_cobro": "2026-11-10"}, headers=gestor)

    assert (guardado.status_code, guardado.json()["cobranza"]["fecha_cobro"]) == (200, "2026-11-09")
    assert (editado.status_code, editado.json()["cobranza"]["fecha_cobro"]) == (200, "2026-11-10")


def test_a_tactical_back_to_pending_keeps_its_record_refuses_edits_and_can_undo_it(
    client, db, productos, gestor, admin_user
) -> None:
    tactical_id = _crear(client, gestor)
    client.post(f"{BASE}/{tactical_id}/aprobar", headers=gestor)
    assert client.put(f"{BASE}/{tactical_id}/cobranza", json=COBRO, headers=gestor).status_code == 200
    assert service.a_pendiente(db, tactical_id, admin_user.id, "money edit")
    db.commit()

    editar = client.put(f"{BASE}/{tactical_id}/cobranza", json={"fecha_cobro": "2026-11-12"}, headers=gestor)
    assert (editar.status_code, _message(editar)) == (409, "Se aprueba antes de cobrar")
    db.expire_all()
    assert str(db.query(TacticalCobranza.fecha_cobro).filter_by(tactical_id=tactical_id).scalar()) == "2026-11-09"

    deshecho = client.delete(f"{BASE}/{tactical_id}/cobranza", headers=gestor)

    assert (deshecho.status_code, deshecho.json()["cobranza"], deshecho.json()["estado"]) == (200, None, "pendiente")
    assert _cobranzas(db, tactical_id) == 0
