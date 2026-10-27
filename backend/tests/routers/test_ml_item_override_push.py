"""`POST /api/ml-item-overrides/{item_id}/ml`: push the publication's override to ML ("Actualizar en ML").

The service decides (`test_ml_item_override_push_service.py`); this file proves the router gates it behind
`ml_publicaciones.editar_publicacion`, passes the caller through, and maps each outcome to its HTTP answer.
"""

from __future__ import annotations

import pytest

from app.routers import ml_item_overrides as router_module
from app.services import ml_item_override_push_service as push
from tests.routers.test_ml_publications_links import grant

URL = "/api/ml-item-overrides/MLA123/ml"


class Service:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.outcome = push.PushOutcome(push.SENT, None, (push.Parte("titulo", push.SUBMITTED, None),))

    async def __call__(self, mla, usuario_id):
        self.calls.append((mla, usuario_id))
        return self.outcome


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch) -> Service:
    fake = Service()
    monkeypatch.setattr(router_module, "push_override", fake)
    return fake


@pytest.fixture()
def allowed(db, rol_admin, admin_auth_headers) -> dict:
    grant(db, rol_admin, "ml_publicaciones.editar_publicacion")
    return admin_auth_headers


def test_without_the_permission_it_is_403_and_nothing_is_sent(client, rol_admin, admin_auth_headers, service) -> None:
    assert client.post(URL, headers=admin_auth_headers).status_code == 403
    assert service.calls == []


def test_it_passes_the_item_and_the_caller_and_answers_each_field(client, allowed, admin_user, service) -> None:
    res = client.post(URL, headers=allowed)
    assert res.status_code == 200
    assert res.json() == {
        "status": push.SENT,
        "message": None,
        "partes": [{"campo": "titulo", "estado": push.SUBMITTED, "motivo": None}],
    }
    assert service.calls == [("MLA123", admin_user.id)]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (push.NOTHING, 200),
        (push.NOT_FOUND, 404),
        (push.NOT_ELIGIBLE, 409),
        (push.DISABLED, 503),
        (push.NOT_SENT, 503),
        (push.UNKNOWN_STATUS, 503),
    ],
)
def test_each_outcome_has_its_http_answer(client, allowed, service, status: str, code: int) -> None:
    service.outcome = push.PushOutcome(status, "motivo", ())
    res = client.post(URL, headers=allowed)
    assert (res.status_code, res.json()["status"], res.json()["message"]) == (code, status, "motivo")


def test_an_item_id_that_is_not_an_mla_is_422(client, allowed, service) -> None:
    assert client.post("/api/ml-item-overrides/DROP%20TABLE/ml", headers=allowed).status_code == 422
    assert service.calls == []
