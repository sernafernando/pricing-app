"""
Integration tests for stock-status and stock-refresh endpoints (TASK-stock).

Covers:
  - GET /api/consultas/ranking/stock-status → 200 (auth + mock DB MAX(updated_at))
  - POST /api/consultas/ranking/stock-refresh → 202 started (run_sync patched to no-op)
  - POST /api/consultas/ranking/stock-refresh → 409 on concurrent call
  - No JWT → 401/403 on both endpoints

Permission is mocked via PermisosService to avoid DB seed dependency.
run_sync is patched to a no-op coroutine so the ERP is never hit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.models.rol import Rol


# ---------------------------------------------------------------------------
# Permission patch helpers (mirrors test_consultas_ranking.py)
# ---------------------------------------------------------------------------

_PATCH_PERMISO_TRUE = patch(
    "app.services.permisos_service.PermisosService.tiene_permiso",
    return_value=True,
)
_PATCH_PERMISO_FALSE = patch(
    "app.services.permisos_service.PermisosService.tiene_permiso",
    return_value=False,
)
_PATCH_OBTENER_PERMISOS = patch(
    "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
    return_value={"consultas.ver_ranking"},
)
_PATCH_OBTENER_PERMISOS_EMPTY = patch(
    "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
    return_value=set(),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def rol_consultas_stock(db) -> Rol:
    """CONSULTAS role for stock endpoint tests."""
    rol = Rol(codigo="CONSULTAS_STOCK", nombre="Consultas Stock", es_sistema=False, orden=21, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def user_con_permiso(db, rol_consultas_stock) -> Usuario:
    """User that HAS consultas.ver_ranking."""
    user = Usuario(
        username="consultas_stock_user",
        email="consultas_stock@example.com",
        nombre="Consultas Stock User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_consultas_stock.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def user_sin_permiso(db, rol_consultas_stock) -> Usuario:
    """User that does NOT have consultas.ver_ranking."""
    user = Usuario(
        username="stock_noperm_user",
        email="stock_noperm@example.com",
        nombre="Stock NoPerm User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_consultas_stock.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _auth(user: Usuario) -> dict:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Mock DB factory for stock-status
# ---------------------------------------------------------------------------


def _make_stock_status_mock_db(last_updated: str | None = "2025-06-01T10:00:00") -> MagicMock:
    """Return a mock DB where MAX(updated_at) returns the given timestamp."""
    result = MagicMock()
    result.fetchone.return_value = (last_updated,)

    mock_db = MagicMock()
    mock_db.execute.return_value = result
    return mock_db


def _make_client_with_stock_mock(user_con_permiso, last_updated):
    """Create a TestClient that overrides both get_db and get_async_db with a
    stock-status mock. The mock handles the raw SQL execute call (MAX(updated_at))
    while ORM-based calls (get_current_user) go through MagicMock's auto-return."""
    from app.core.database import get_async_db, get_db
    from app.main import app

    mock_db = _make_stock_status_mock_db(last_updated)

    def _override_get_db():
        yield mock_db

    async def _override_get_async_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_async_db] = _override_get_async_db

    from starlette.testclient import TestClient

    return TestClient(app, raise_server_exceptions=False), user_con_permiso


@pytest.fixture()
def client_stock_status(user_con_permiso):
    """TestClient with a mock DB returning a fixed last_updated timestamp."""
    from app.core.database import get_async_db, get_db
    from app.main import app

    mock_db = _make_stock_status_mock_db("2025-06-01T10:00:00")

    def _override_get_db():
        yield mock_db

    async def _override_get_async_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_async_db] = _override_get_async_db

    from starlette.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, user_con_permiso

    app.dependency_overrides.clear()


@pytest.fixture()
def client_stock_status_empty(user_con_permiso):
    """TestClient with a mock DB returning NULL last_updated (empty table)."""
    from app.core.database import get_async_db, get_db
    from app.main import app

    mock_db = _make_stock_status_mock_db(None)

    def _override_get_db():
        yield mock_db

    async def _override_get_async_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_async_db] = _override_get_async_db

    from starlette.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, user_con_permiso

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers: reset the module-level concurrency guard between tests
# ---------------------------------------------------------------------------


def _reset_sync_guard() -> None:
    """Force _stock_sync_running = False and clear background tasks so tests start clean."""
    import app.routers.consultas as mod

    mod._stock_sync_running = False
    mod._background_tasks.clear()


# ---------------------------------------------------------------------------
# Tests: GET /api/consultas/ranking/stock-status
# ---------------------------------------------------------------------------


class TestStockStatus:
    """Tests for GET /api/consultas/ranking/stock-status."""

    def test_no_jwt_returns_401_or_403(self, client) -> None:
        """No Authorization header → 401 or 403."""
        response = client.get("/api/consultas/ranking/stock-status")
        assert response.status_code in (401, 403)

    def test_user_sin_permiso_returns_403(self, client, user_sin_permiso) -> None:
        """Valid JWT without consultas.ver_ranking → 403."""
        with _PATCH_PERMISO_FALSE, _PATCH_OBTENER_PERMISOS_EMPTY:
            response = client.get(
                "/api/consultas/ranking/stock-status",
                headers=_auth(user_sin_permiso),
            )
        assert response.status_code == 403

    def test_returns_200_with_last_updated(self, client_stock_status) -> None:
        """Authorized request → 200 with last_updated and syncing=False."""
        client, user = client_stock_status
        with _PATCH_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.get(
                "/api/consultas/ranking/stock-status",
                headers=_auth(user),
            )
        assert response.status_code == 200
        body = response.json()
        assert "last_updated" in body
        assert body["last_updated"] is not None
        assert body["syncing"] is False

    def test_returns_null_last_updated_when_empty(self, client_stock_status_empty) -> None:
        """When stock_por_deposito is empty MAX returns NULL → last_updated=null."""
        client, user = client_stock_status_empty
        with _PATCH_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.get(
                "/api/consultas/ranking/stock-status",
                headers=_auth(user),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["last_updated"] is None
        assert body["syncing"] is False


# ---------------------------------------------------------------------------
# Tests: POST /api/consultas/ranking/stock-refresh
# ---------------------------------------------------------------------------


class TestStockRefresh:
    """Tests for POST /api/consultas/ranking/stock-refresh."""

    def setup_method(self) -> None:
        """Reset the concurrency guard before each test."""
        _reset_sync_guard()

    def test_no_jwt_returns_401_or_403(self, client) -> None:
        """No Authorization header → 401 or 403."""
        response = client.post("/api/consultas/ranking/stock-refresh")
        assert response.status_code in (401, 403)

    def test_user_sin_permiso_returns_403(self, client, user_sin_permiso) -> None:
        """Valid JWT without consultas.ver_ranking → 403."""
        with _PATCH_PERMISO_FALSE, _PATCH_OBTENER_PERMISOS_EMPTY:
            response = client.post(
                "/api/consultas/ranking/stock-refresh",
                headers=_auth(user_sin_permiso),
            )
        assert response.status_code == 403

    def test_returns_202_started(self, client, user_con_permiso) -> None:
        """Authorized first call → 202 with status='started'.

        run_sync is patched to an async no-op so the ERP is never hit.
        asyncio.create_task is patched so the coroutine is discarded (avoids
        needing a running event loop for the test task to settle).
        """
        # Patch run_sync to a coroutine that returns immediately
        noop_coro = AsyncMock(return_value=None)

        with (
            _PATCH_PERMISO_TRUE,
            _PATCH_OBTENER_PERMISOS,
            patch("app.scripts.sync_stock_por_deposito.run_sync", noop_coro),
            patch("asyncio.create_task", return_value=MagicMock()),
        ):
            response = client.post(
                "/api/consultas/ranking/stock-refresh",
                headers=_auth(user_con_permiso),
            )

        _reset_sync_guard()  # guard was set True by the endpoint

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "started"

    def test_background_task_resets_guard(self) -> None:
        """The background task must hold a strong reference and reset the guard.

        Drives _run_and_reset to completion (not mocking create_task) and asserts
        the guard flips back to False, so a GC'd/finished task can never leave the
        endpoint stuck at 409. Regression for the dropped-task footgun.
        """
        import asyncio

        import app.routers.consultas as mod
        from app.routers.consultas import post_stock_refresh

        mod._stock_sync_running = False
        mod._background_tasks.clear()
        noop = AsyncMock(return_value=None)

        async def _drive():
            with patch("app.scripts.sync_stock_por_deposito.run_sync", noop):
                response = await post_stock_refresh()
                # The task is scheduled on this loop; await it to completion.
                await asyncio.gather(*list(mod._background_tasks))
            return response

        response = asyncio.run(_drive())

        assert response.status == "started"
        assert noop.await_count == 1
        assert mod._stock_sync_running is False
        assert mod._background_tasks == set()

    def test_concurrent_call_returns_409(self, client, user_con_permiso) -> None:
        """While a sync is in progress a second call → 409."""
        import app.routers.consultas as mod

        # Simulate an in-progress sync
        mod._stock_sync_running = True

        with _PATCH_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.post(
                "/api/consultas/ranking/stock-refresh",
                headers=_auth(user_con_permiso),
            )

        _reset_sync_guard()

        assert response.status_code == 409
        body = response.json()
        body_str = str(body).lower()
        assert "curso" in body_str or "en curso" in body_str or "sincroniz" in body_str
