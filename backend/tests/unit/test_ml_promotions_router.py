"""
Unit tests for the ml_promotions router (READ-ONLY, PR1).

Endpoints under test (prefix /api/promociones):
  GET /api/promociones                       -> list promotions (table)
  GET /api/promociones/{promotion_id}/items   -> items of a promotion (table)
  GET /api/promociones/item/{mla_id}          -> promotions of a single MLA (table)

Write endpoints (enroll/remove) are PR2 and are NOT covered here.

Spec coverage:
  REQ-1 — ML_WEBHOOK_DB_URL unset -> 503 on every read endpoint, before any
          service call touches the DB
  REQ-2 — missing promos.ver permission -> 403, no downstream call
  REQ-3 — GET list (table) happy path
  REQ-4 — GET promo items missing promotion_type -> 422
  REQ-5 — GET promo items happy path (promotion_type required, present)
  REQ-6 — GET per-item promotions happy path, status mapping passthrough
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.usuario import Usuario


def _fake_user() -> Usuario:
    user = Usuario()
    user.id = 1
    user.username = "tester"
    return user


class _FakePermisosService:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.calls: list[str] = []

    def tiene_permiso(self, usuario, codigo: str) -> bool:
        self.calls.append(codigo)
        return self.allowed


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _override_auth(allowed_permiso: bool = True):
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_db] = lambda: iter([None]).__next__() or object()

    fake_service = _FakePermisosService(allowed_permiso)
    return fake_service


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


class TestPermissionGate:
    def test_missing_permission_returns_403(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=False)
        try:
            with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
                response = client.get("/api/promociones")
        finally:
            _clear_overrides()

        assert response.status_code == 403
        assert "promos.ver" in fake_service.calls


class TestDbUnavailable:
    def test_list_promotions_503_when_db_url_unset(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_promotions",
                    side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
                ),
            ):
                response = client.get("/api/promociones")
        finally:
            _clear_overrides()

        assert response.status_code == 503

    def test_promotion_items_503_when_db_url_unset(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_promotion_items",
                    side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
                ),
            ):
                response = client.get("/api/promociones/DEAL-1/items", params={"promotion_type": "DEAL"})
        finally:
            _clear_overrides()

        assert response.status_code == 503

    def test_item_promotions_503_when_db_url_unset(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_item_promotions",
                    side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
                ),
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 503


class TestListPromotions:
    def test_happy_path(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_promotions",
                    return_value=[
                        {
                            "promotion_id": "SELLER_CAMPAIGN",
                            "promotion_type": "SELLER_CAMPAIGN",
                            "sub_type": None,
                            "status": "started",
                            "name": "Campaña Vendedor",
                            "start_date": None,
                            "finish_date": None,
                            "deadline_date": None,
                            "payload": {},
                            "updated_at": None,
                        }
                    ],
                ),
            ):
                response = client.get("/api/promociones")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["promotions"][0]["promotion_id"] == "SELLER_CAMPAIGN"


class TestPromotionItems:
    def test_missing_promotion_type_returns_422(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
                response = client.get("/api/promociones/DEAL-1/items")
        finally:
            _clear_overrides()

        assert response.status_code == 422

    def test_happy_path(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_promotion_items",
                    return_value=[
                        {
                            "mla": "MLA111",
                            "promotion_id": "DEAL-1",
                            "promotion_type": "DEAL",
                            "sub_type": None,
                            "status": "candidate",
                            "original_price": 1000.0,
                            "price": 900.0,
                            "min_discounted_price": 850.0,
                            "max_discounted_price": 950.0,
                            "suggested_discounted_price": 900.0,
                            "payload": {},
                            "updated_at": None,
                        }
                    ],
                ),
            ):
                response = client.get("/api/promociones/DEAL-1/items", params={"promotion_type": "DEAL"})
        finally:
            _clear_overrides()

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["items"][0]["mla"] == "MLA111"


class TestItemPromotions:
    def test_happy_path_status_mapping(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.fetch_item_promotions",
                    return_value=[
                        {
                            "mla": "MLA123456789",
                            "promotion_id": "DEAL-1",
                            "promotion_type": "DEAL",
                            "sub_type": None,
                            "status": "started",
                            "original_price": 1000.0,
                            "price": 900.0,
                            "min_discounted_price": 850.0,
                            "max_discounted_price": 950.0,
                            "suggested_discounted_price": 900.0,
                            "payload": {},
                            "updated_at": None,
                        }
                    ],
                ) as mock_fetch,
            ):
                response = client.get("/api/promociones/item/MLA123456789")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["promotions"][0]["status"] == "started"
        # The endpoint must request only candidate|started promotions: the
        # backfilled ml_item_promotions table is upsert-only with no stale
        # cleanup, so finished promos would otherwise linger in the display.
        mock_fetch.assert_called_once_with("MLA123456789", active_only=True)
