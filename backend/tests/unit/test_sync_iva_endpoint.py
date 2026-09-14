"""
Tests for `POST /sync-iva` (thin HTTP layer over `sync_item_taxes_full`).

`sync_item_taxes_full` never raises: on ERP failure it swallows the exception
and returns a dict carrying an `"error"` key. The endpoint must inspect that
dict itself and turn it into a 500 instead of returning 200 with a hidden
failure inside the body.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_admin_or_localhost
from app.core.database import get_async_db
from app.main import app
from app.models.usuario import RolUsuario, Usuario


@pytest.fixture()
def admin_user() -> Usuario:
    return Usuario(
        id=1,
        username="sync_iva_admin",
        email="sync_iva_admin@example.com",
        nombre="Sync Iva Admin",
        rol=RolUsuario.ADMIN,
        activo=True,
    )


@pytest.fixture()
def client(admin_user, db):
    def _override_get_async_db():
        yield db

    def _override_get_admin_or_localhost():
        return admin_user

    app.dependency_overrides[get_async_db] = _override_get_async_db
    app.dependency_overrides[get_admin_or_localhost] = _override_get_admin_or_localhost

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()


class TestSyncIvaEndpoint:
    def test_happy_path_returns_result_dict(self, client) -> None:
        with patch(
            "app.api.endpoints.sync.sync_item_taxes_full",
            new=AsyncMock(return_value={"insertados": 5, "items_reemplazados": 3}),
        ):
            response = client.post("/api/sync-iva")

        assert response.status_code == 200
        assert response.json() == {"insertados": 5, "items_reemplazados": 3}

    def test_error_in_result_dict_returns_500(self, client) -> None:
        with patch(
            "app.api.endpoints.sync.sync_item_taxes_full",
            new=AsyncMock(return_value={"insertados": 0, "items_reemplazados": 0, "error": "connection refused"}),
        ):
            response = client.post("/api/sync-iva")

        assert response.status_code == 500
