"""Bulk pause / activate over the publications a Publicaciones ML filter shows (publicaciones-ml-producto-propio T5).

`GET /api/ml-publications/view/status-item-ids` names the MLAs of the filtered set that can take the target status
(only an active publication is paused, only a paused one activated, never a deleted one) and how many of the set
cannot; over the cap it refuses (422), never truncates. `POST /api/ml-publications/items/status-bulk` writes one
small batch of them, each through the single-publication service, which checks every one again.

Same harness as `/product-ids`: the store in a throwaway Postgres schema.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest

from app.routers import ml_item_status as status_router
from app.services import ml_item_status_write_service as write_service
from app.services.ml_publications.view import status_targets
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

URL = "/api/ml-publications/view/status-item-ids"
BULK_URL = "/api/ml-publications/items/status-bulk"
PAUSAR = "ml_publicaciones.pausar"


def fill(conn) -> None:
    seed.add_product(conn, 77, "R77", "Router AX", marca="TP-Link", stock=4)
    seed.add_item(conn, "MLA1", status="active", title="Router uno")
    seed.add_item(conn, "MLA2", status="active", title="Router dos")
    seed.add_item(conn, "MLA3", status="paused", title="Router tres")
    seed.add_item(conn, "MLA4", status="inactive", sub_status=["deleted"], title="Router borrado")
    seed.add_item(conn, "MLA5", status="closed", title="Router cerrado")
    seed.add_item(conn, "MLA6", status="paused", sub_status=["out_of_stock"], title="Antena")
    seed.add_link(conn, "MLA1", 77)


@pytest.fixture()
def rows(pg):
    seed_rows(pg, fill)


@pytest.fixture()
def allowed(db, rol_admin, admin_auth_headers) -> dict:
    grant(db, rol_admin, VER, PAUSAR)
    return admin_auth_headers


def body(client, headers, **params) -> dict:
    response = client.get(URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.postgres
class TestStatusItemIds:
    def test_ml_ops_ver_alone_is_not_enough(self, client, rows, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER)
        response = client.get(URL, headers=admin_auth_headers, params={"target": "paused"})
        assert response.status_code == 403 and PAUSAR in response.json()["error"]["message"]

    def test_pausing_names_the_active_ones_and_counts_the_rest(self, client, rows, allowed) -> None:
        # The default list hides the deleted MLA4: the set is MLA1, MLA2, MLA3, MLA5, MLA6.
        assert body(client, allowed, target="paused") == {"item_ids": ["MLA1", "MLA2"], "count": 2, "no_aplican": 3}

    def test_activating_names_the_paused_ones(self, client, rows, allowed) -> None:
        assert body(client, allowed, target="active") == {"item_ids": ["MLA3", "MLA6"], "count": 2, "no_aplican": 3}

    def test_the_filters_narrow_the_set(self, client, rows, allowed) -> None:
        assert body(client, allowed, target="paused", q="Antena") == {"item_ids": [], "count": 0, "no_aplican": 1}
        assert body(client, allowed, target="active", estado="paused") == {
            "item_ids": ["MLA3", "MLA6"],
            "count": 2,
            "no_aplican": 0,
        }

    def test_a_deleted_publication_is_never_named_even_when_the_filter_shows_it(self, client, rows, allowed) -> None:
        assert body(client, allowed, target="active", estado="gone") == {"item_ids": [], "count": 0, "no_aplican": 1}

    def test_over_the_cap_it_refuses_with_the_count(self, client, rows, allowed, monkeypatch) -> None:
        monkeypatch.setattr(status_targets, "MAX_STATUS_ITEM_IDS", 1)
        response = client.get(URL, headers=allowed, params={"target": "paused"})
        assert response.status_code == 422
        detail = response.json()["error"]
        assert (detail["count"], detail["max"]) == (2, 1)

    def test_a_markup_filter_is_honored_so_it_needs_ver_ganancia(self, client, rows, allowed) -> None:
        # Ignoring it would pause more than the operator sees: the filter is applied, hence its permission.
        response = client.get(URL, headers=allowed, params={"target": "paused", "markup_neg": "true"})
        assert response.status_code == 403 and "ml_metricas.ver_ganancia" in response.json()["error"]["message"]

    @pytest.mark.parametrize("target", ["", "closed", "PAUSED"])
    def test_a_target_other_than_paused_or_active_is_422(self, client, rows, allowed, target) -> None:
        assert client.get(URL, headers=allowed, params={"target": target}).status_code == 422


class Service:
    """Stands in for `set_item_status`: records each call, answers per MLA."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def __call__(self, mla, target, usuario_id):
        self.calls.append((mla, target, usuario_id))
        if mla == "MLA2":
            return write_service.ItemStatusOutcome(write_service.REJECTED, "item has no stock")
        return write_service.ItemStatusOutcome(write_service.SUBMITTED, None)


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch) -> Service:
    fake = Service()
    monkeypatch.setattr(status_router, "set_item_status", fake)
    return fake


@pytest.fixture()
def can_pause(db, rol_admin, admin_auth_headers) -> dict:
    grant(db, rol_admin, PAUSAR)
    return admin_auth_headers


class TestBulk:
    def test_without_the_permission_it_is_403_and_nothing_is_written(
        self, client, rol_admin, admin_auth_headers, service
    ) -> None:
        response = client.post(BULK_URL, headers=admin_auth_headers, json={"status": "paused", "item_ids": ["MLA1"]})
        assert response.status_code == 403
        assert service.calls == []

    def test_writes_each_one_in_order_and_answers_each(self, client, can_pause, admin_user, service) -> None:
        response = client.post(
            BULK_URL, headers=can_pause, json={"status": "paused", "item_ids": ["MLA1", "MLA2", "MLA3"]}
        )
        assert response.status_code == 200
        assert response.json() == {
            "results": [
                {"item_id": "MLA1", "status": "submitted", "message": None},
                {"item_id": "MLA2", "status": "rejected", "message": "item has no stock"},
                {"item_id": "MLA3", "status": "submitted", "message": None},
            ]
        }
        assert service.calls == [(mla, "paused", admin_user.id) for mla in ("MLA1", "MLA2", "MLA3")]

    def test_a_repeated_mla_is_written_once(self, client, can_pause, service) -> None:
        client.post(BULK_URL, headers=can_pause, json={"status": "active", "item_ids": ["MLA1", "MLA1"]})
        assert [call[0] for call in service.calls] == ["MLA1"]

    @pytest.mark.parametrize(
        "payload",
        [
            {"status": "paused", "item_ids": []},
            {"status": "paused", "item_ids": ["123"]},
            {"status": "closed", "item_ids": ["MLA1"]},
            {"status": "paused", "item_ids": [f"MLA{n}" for n in range(status_router.BULK_BATCH_SIZE + 1)]},
        ],
    )
    def test_an_invalid_batch_is_422_and_nothing_is_written(self, client, can_pause, service, payload) -> None:
        assert client.post(BULK_URL, headers=can_pause, json=payload).status_code == 422
        assert service.calls == []
