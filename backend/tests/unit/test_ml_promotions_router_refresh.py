"""
Unit tests for the per-item promo-refresh endpoint on the ml_promotions
router (per-MLA manual refresh button).

  POST /api/promociones/item/{mla_id}/refresh   -> RefreshResult,
  gated by promos.escribir (same permission as enroll/remove).

Spec coverage:
  REQ-1 — happy path -> 200 {"ok": true}
  REQ-2 — proxy failure (refresh_item_promotions returns False, never
          raises) -> 200 {"ok": false} (FAIL-SOFT, never 500)
  REQ-3 — missing promos.escribir -> 403, no downstream call
  REQ-4 — unauthenticated -> 401 (handled by get_current_user dependency)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException, status
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


def _unauthenticated() -> Usuario:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")


class TestRefreshEndpoint:
    def test_happy_path_returns_ok_true(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.ml_webhook_client.refresh_item_promotions",
                    return_value=True,
                ),
            ):
                response = client.post("/api/promociones/item/MLA123456789/refresh")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_proxy_failure_returns_200_ok_false(self, client: TestClient) -> None:
        """refresh_item_promotions never raises — it returns False on any
        error (proxy down, 404, timeout). That must surface as {ok: false}
        with HTTP 200, NEVER a 500."""
        fake_service = _override_auth(allowed_permiso=True)
        try:
            with (
                patch("app.routers.ml_promotions.PermisosService", return_value=fake_service),
                patch(
                    "app.routers.ml_promotions.ml_webhook_client.refresh_item_promotions",
                    return_value=False,
                ),
            ):
                response = client.post("/api/promociones/item/MLA123456789/refresh")
        finally:
            _clear_overrides()

        assert response.status_code == 200
        assert response.json() == {"ok": False}

    def test_missing_permission_returns_403(self, client: TestClient) -> None:
        fake_service = _override_auth(allowed_permiso=False)
        try:
            with patch("app.routers.ml_promotions.PermisosService", return_value=fake_service):
                response = client.post("/api/promociones/item/MLA123456789/refresh")
        finally:
            _clear_overrides()

        assert response.status_code == 403
        assert "promos.escribir" in fake_service.calls

    def test_unauthenticated_returns_401(self, client: TestClient) -> None:
        app.dependency_overrides[get_current_user] = _unauthenticated
        try:
            response = client.post("/api/promociones/item/MLA123456789/refresh")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 401
