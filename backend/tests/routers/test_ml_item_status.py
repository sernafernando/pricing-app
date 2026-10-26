"""`POST /api/ml-publications/items/{item_id}/status`: pause or activate one publication.

The service decides (`test_ml_item_status_write_service.py`); this file proves the router gates it behind
`ml_publicaciones.pausar`, passes the caller through, and maps each outcome to its HTTP answer.
"""

from __future__ import annotations

import pytest

from app.routers import ml_item_status as router_module
from app.services import ml_item_status_write_service as write_service
from tests.routers.test_ml_publications_links import grant

URL = "/api/ml-publications/items/MLA123/status"


class Service:
    """Stands in for `set_item_status`: records each call and answers `outcome`."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.outcome = write_service.ItemStatusOutcome(write_service.SUBMITTED, None)

    async def __call__(self, db, mla, target, usuario_id):
        self.calls.append((mla, target, usuario_id))
        return self.outcome


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch) -> Service:
    fake = Service()
    monkeypatch.setattr(router_module, "set_item_status", fake)
    return fake


@pytest.fixture()
def allowed(db, rol_admin, admin_auth_headers) -> dict:
    grant(db, rol_admin, "ml_publicaciones.pausar")
    return admin_auth_headers


def test_without_the_permission_it_is_403_and_nothing_is_written(
    client, rol_admin, admin_auth_headers, service
) -> None:
    res = client.post(URL, json={"status": "paused"}, headers=admin_auth_headers)
    assert res.status_code == 403
    assert service.calls == []


def test_it_passes_the_item_the_target_and_the_caller(client, allowed, admin_user, service) -> None:
    res = client.post(URL, json={"status": "active"}, headers=allowed)
    assert res.status_code == 200
    assert res.json() == {"status": write_service.SUBMITTED, "message": None}
    assert service.calls == [("MLA123", "active", admin_user.id)]


@pytest.mark.parametrize("body", [{}, {"status": "closed"}, {"status": "PAUSED"}])
def test_a_status_other_than_paused_or_active_is_422(client, allowed, service, body) -> None:
    assert client.post(URL, json=body, headers=allowed).status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    "outcome, code",
    [
        (write_service.UNCHANGED, 200),
        (write_service.AMBIGUOUS, 202),
        (write_service.NOT_ELIGIBLE, 409),
        (write_service.REJECTED, 422),
        (write_service.DISABLED, 503),
    ],
)
def test_each_outcome_has_its_answer_with_the_message(client, allowed, service, outcome, code) -> None:
    service.outcome = write_service.ItemStatusOutcome(outcome, "why")
    res = client.post(URL, json={"status": "paused"}, headers=allowed)
    assert res.status_code == code
    assert res.json() == {"status": outcome, "message": "why"}
