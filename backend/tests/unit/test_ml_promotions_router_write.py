"""
Unit tests for the WRITE endpoints on the ml_promotions router (PR2/T6).

  POST   /api/promociones/item/{mla_id}   -> EnrollResult, gated by promos.escribir
  DELETE /api/promociones/item/{mla_id}   -> RemoveResult, gated by promos.escribir

Spec coverage:
  REQ-1 — missing promos.escribir -> 403, no downstream call
  REQ-2 — kill-switch disabled outcome -> mapped to a clear HTTP status (403)
  REQ-3 — enroll happy path -> 200 EnrollResult, status=submitted
  REQ-4 — enroll rejected_out_of_range -> 422
  REQ-5 — enroll rejected_unsupported_type -> 400/422
  REQ-6 — RuntimeError (ML_WEBHOOK_DB_URL unset) -> 503
  REQ-7 — remove happy path -> 200 RemoveResult
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


class TestWritePermissionGate:
    def test_enroll_missing_permission_returns_403(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=False)
        try:
            with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1", "promotion_type": "DEAL"},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 403
        assert "promos.escribir" in fake_service.calls

    def test_remove_missing_permission_returns_403(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=False)
        try:
            with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
                response = client.delete(
                    "/api/promociones/item/MLA123456789",
                    params={"promotion_type": "DEAL", "promotion_id": "DEAL-1"},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 403
        assert "promos.escribir" in fake_service.calls


class TestEnrollEndpoint:
    def test_happy_path_returns_submitted(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.enroll_one_item",
                    return_value={"submitted": True, "status": "submitted", "price": 900.0, "status_code": 201},
                ),
            ):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1", "promotion_type": "DEAL", "deal_price": 900.0},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        body = response.json()
        assert body["submitted"] is True
        assert body["status"] == "submitted"

    def test_disabled_kill_switch_maps_to_403(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.enroll_one_item",
                    return_value={"submitted": False, "status": "disabled", "detail": "writes disabled"},
                ),
            ):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1", "promotion_type": "DEAL"},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 403

    def test_out_of_range_maps_to_422(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.enroll_one_item",
                    return_value={
                        "submitted": False,
                        "status": "rejected_out_of_range",
                        "detail": "deal_price outside range",
                    },
                ),
            ):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1", "promotion_type": "DEAL", "deal_price": 5000.0},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 422

    def test_unsupported_type_maps_to_422(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.enroll_one_item",
                    return_value={
                        "submitted": False,
                        "status": "rejected_unsupported_type",
                        "detail": "not writable",
                    },
                ),
            ):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "SMART-1", "promotion_type": "SMART"},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 422

    def test_db_unavailable_returns_503(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.enroll_one_item",
                    side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
                ),
            ):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1", "promotion_type": "DEAL", "deal_price": 900.0},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 503

    def test_ambiguous_returns_202(self, client: TestClient) -> None:
        """Definitive-vs-ambiguous fix: `ambiguous` (write submitted, outcome
        genuinely unknown) must be 202 Accepted, NOT 200 or a rejection."""
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.enroll_one_item",
                    return_value={
                        "submitted": False,
                        "status": "ambiguous",
                        "status_code": 500,
                        "reconciled_row": None,
                    },
                ),
            ):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1", "promotion_type": "DEAL", "deal_price": 900.0},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 202
        assert response.json()["status"] == "ambiguous"

    def test_rejected_by_proxy_is_not_200(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.enroll_one_item",
                    return_value={
                        "submitted": False,
                        "status": "rejected_by_proxy",
                        "status_code": 400,
                        "detail": {"message": "invalid price"},
                    },
                ),
            ):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1", "promotion_type": "DEAL", "deal_price": 900.0},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 422
        assert response.status_code != 200

    def test_rejected_read_unavailable_maps_to_503(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.enroll_one_item",
                    return_value={
                        "submitted": False,
                        "status": "rejected_read_unavailable",
                        "detail": "live read failed",
                    },
                ),
            ):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1", "promotion_type": "DEAL", "deal_price": 900.0},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 503

    def test_rejected_promotion_not_found_maps_to_422(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.enroll_one_item",
                    return_value={
                        "submitted": False,
                        "status": "rejected_promotion_not_found",
                        "detail": "not present in live payload",
                    },
                ),
            ):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1", "promotion_type": "DEAL", "deal_price": 900.0},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 422

    def test_rejected_price_unresolved_maps_to_422(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.enroll_one_item",
                    return_value={
                        "submitted": False,
                        "status": "rejected_price_unresolved",
                        "detail": "no price could be resolved",
                    },
                ),
            ):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1", "promotion_type": "DEAL"},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 422

    def test_missing_promotion_type_returns_422(self, client: TestClient) -> None:
        """promotion_type is a required body field — omitting it must fail
        request validation (422) before ever reaching the service."""
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1"},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 422

    def test_ambiguous_reconciled_applied_returns_200(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.enroll_one_item",
                    return_value={
                        "submitted": False,
                        "status": "reconciled_applied",
                        "status_code": None,
                        "reconciled_row": {"status": "started"},
                    },
                ),
            ):
                response = client.post(
                    "/api/promociones/item/MLA123456789",
                    json={"promotion_id": "DEAL-1", "promotion_type": "DEAL", "deal_price": 900.0},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        assert response.json()["status"] == "reconciled_applied"


class TestRemoveEndpoint:
    def test_happy_path_returns_submitted(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.remove_one_item",
                    return_value={"submitted": True, "status": "submitted", "status_code": 200},
                ),
            ):
                response = client.delete(
                    "/api/promociones/item/MLA123456789",
                    params={"promotion_type": "DEAL", "promotion_id": "DEAL-1"},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 200
        assert response.json()["submitted"] is True

    def test_disabled_kill_switch_maps_to_403(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.remove_one_item",
                    return_value={"submitted": False, "status": "disabled", "detail": "writes disabled"},
                ),
            ):
                response = client.delete(
                    "/api/promociones/item/MLA123456789",
                    params={"promotion_type": "DEAL", "promotion_id": "DEAL-1"},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 403

    def test_ambiguous_returns_202(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.remove_one_item",
                    return_value={
                        "submitted": False,
                        "status": "ambiguous",
                        "status_code": 500,
                        "reconciled_row": None,
                    },
                ),
            ):
                response = client.delete(
                    "/api/promociones/item/MLA123456789",
                    params={"promotion_type": "DEAL", "promotion_id": "DEAL-1"},
                )
        finally:
            _clear_overrides()

        assert response.status_code == 202
