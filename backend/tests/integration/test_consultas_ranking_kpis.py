"""
Integration tests for GET /api/consultas/ranking/kpis.

Covers:
  - No JWT → 401 or 403 (HTTPBearer default)
  - Valid JWT without consultas.ver_ranking → 403
  - Valid JWT with consultas.ver_ranking → 200 with expected KPI shape
  - Response fields: total_productos, stock_total, capital_costo_ars,
    capital_costo_usd, capital_venta_ars, capital_muerto_ars, pct_capital_muerto

Permission is mocked via PermisosService to avoid DB seed dependency.
Mock DB avoids PostgreSQL-specific SQL (LATERAL, ANY) not supported by SQLite.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.models.rol import Rol


# ---------------------------------------------------------------------------
# Fixtures (shared with test_consultas_ranking.py pattern)
# ---------------------------------------------------------------------------


@pytest.fixture()
def rol_kpis(db) -> Rol:
    """Role for KPI tests."""
    rol = Rol(codigo="KPIS_TEST", nombre="KPIs Test", es_sistema=False, orden=25, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def user_con_permiso_kpis(db, rol_kpis) -> Usuario:
    """User that HAS consultas.ver_ranking."""
    user = Usuario(
        username="kpis_user",
        email="kpis@example.com",
        nombre="KPIs User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_kpis.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def user_sin_permiso_kpis(db, rol_kpis) -> Usuario:
    """User that does NOT have consultas.ver_ranking."""
    user = Usuario(
        username="kpis_noperm",
        email="kpis_noperm@example.com",
        nombre="KPIs NoPerm",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_kpis.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _token(user: Usuario) -> str:
    return create_access_token(data={"sub": user.username})


def _auth(user: Usuario) -> dict:
    return {"Authorization": f"Bearer {_token(user)}"}


_PATCH_TIENE_PERMISO_TRUE = patch(
    "app.services.permisos_service.PermisosService.tiene_permiso",
    return_value=True,
)
_PATCH_TIENE_PERMISO_FALSE = patch(
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
# Mock DB helpers
# ---------------------------------------------------------------------------


def _make_kpis_mock_db_session() -> MagicMock:
    """Return a MagicMock DB session for the /kpis endpoint.

    The KPIs endpoint executes one query returning a single aggregate row.
    _get_tc_venta is patched separately in tests that use this mock.
    """
    kpis_row = MagicMock()
    kpis_row.total_productos = 42
    kpis_row.stock_total = 350
    kpis_row.capital_costo_ars = 12_000_000.0
    kpis_row.capital_costo_usd = 10_000.0
    kpis_row.capital_venta_ars = 18_000_000.0
    kpis_row.capital_muerto_ars = 3_000_000.0
    kpis_row.pct_capital_muerto = 25.0

    result = MagicMock()
    result.fetchone.return_value = kpis_row

    mock_db = MagicMock()
    mock_db.execute.return_value = result
    return mock_db


@pytest.fixture()
def client_with_mock_db_kpis(user_con_permiso_kpis):
    """TestClient with a mock DB session for the /kpis endpoint."""
    from app.core.database import get_async_db, get_db
    from app.main import app
    from starlette.testclient import TestClient

    mock_db = _make_kpis_mock_db_session()

    def _override_get_db():
        yield mock_db

    async def _override_get_async_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_async_db] = _override_get_async_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, user_con_permiso_kpis

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestKpisAuth:
    """Authentication and permission gate tests for /ranking/kpis."""

    def test_no_jwt_returns_401_or_403(self, client) -> None:
        """No Authorization header → 401 or 403 (HTTPBearer default is 403)."""
        response = client.get("/api/consultas/ranking/kpis")
        assert response.status_code in (401, 403)

    def test_user_sin_permiso_returns_403(self, client, user_sin_permiso_kpis) -> None:
        """Valid JWT without consultas.ver_ranking → 403."""
        with _PATCH_TIENE_PERMISO_FALSE, _PATCH_OBTENER_PERMISOS_EMPTY:
            response = client.get(
                "/api/consultas/ranking/kpis",
                headers=_auth(user_sin_permiso_kpis),
            )
        assert response.status_code == 403


class TestKpis200:
    """Shape and value tests for /ranking/kpis 200 response."""

    def test_kpis_returns_200(self, client_with_mock_db_kpis) -> None:
        """Valid JWT with consultas.ver_ranking → 200."""
        client, user = client_with_mock_db_kpis
        with (
            _PATCH_TIENE_PERMISO_TRUE,
            _PATCH_OBTENER_PERMISOS,
            patch("app.routers.consultas._get_tc_venta", return_value=1200.0),
        ):
            response = client.get(
                "/api/consultas/ranking/kpis",
                headers=_auth(user),
            )
        assert response.status_code == 200

    def test_kpis_response_has_expected_fields(self, client_with_mock_db_kpis) -> None:
        """Response exposes all required KPI fields."""
        client, user = client_with_mock_db_kpis
        with (
            _PATCH_TIENE_PERMISO_TRUE,
            _PATCH_OBTENER_PERMISOS,
            patch("app.routers.consultas._get_tc_venta", return_value=1200.0),
        ):
            response = client.get(
                "/api/consultas/ranking/kpis",
                headers=_auth(user),
            )
        assert response.status_code == 200
        body = response.json()
        required_fields = {
            "total_productos",
            "stock_total",
            "capital_costo_ars",
            "capital_costo_usd",
            "capital_venta_ars",
            "capital_muerto_ars",
            "pct_capital_muerto",
        }
        assert required_fields.issubset(body.keys()), f"Missing fields: {required_fields - body.keys()}"

    def test_kpis_response_values_match_mock(self, client_with_mock_db_kpis) -> None:
        """Response values match the mock DB row exactly."""
        client, user = client_with_mock_db_kpis
        with (
            _PATCH_TIENE_PERMISO_TRUE,
            _PATCH_OBTENER_PERMISOS,
            patch("app.routers.consultas._get_tc_venta", return_value=1200.0),
        ):
            response = client.get(
                "/api/consultas/ranking/kpis",
                headers=_auth(user),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["total_productos"] == 42
        assert body["stock_total"] == 350
        assert body["capital_costo_ars"] == 12_000_000.0
        assert body["capital_costo_usd"] == 10_000.0
        assert body["capital_venta_ars"] == 18_000_000.0
        assert body["capital_muerto_ars"] == 3_000_000.0
        assert body["pct_capital_muerto"] == 25.0

    def test_kpis_sql_excludes_stock_sentinel(self, user_con_permiso_kpis) -> None:
        """Regression: the capital query MUST exclude the ERP "no controla stock"
        sentinel (99999999). Without this, those virtual items inflate capital to
        ~$28B USD (prod incident 2026-06-01). Inspect the executed SQL directly,
        since the mock DB does not run LATERAL/ANY."""
        from app.core.database import get_async_db, get_db
        from app.main import app
        from app.routers.consultas import STOCK_SENTINEL
        from starlette.testclient import TestClient

        mock_db = _make_kpis_mock_db_session()

        def _override_get_db():
            yield mock_db

        async def _override_get_async_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_async_db] = _override_get_async_db

        with TestClient(app, raise_server_exceptions=False) as c:
            with (
                _PATCH_TIENE_PERMISO_TRUE,
                _PATCH_OBTENER_PERMISOS,
                patch("app.routers.consultas._get_tc_venta", return_value=1200.0),
            ):
                response = c.get("/api/consultas/ranking/kpis", headers=_auth(user_con_permiso_kpis))

        app.dependency_overrides.clear()
        assert response.status_code == 200

        executed_sql = [
            str(call.args[0])
            for call in mock_db.execute.call_args_list
            if call.args and "stock_por_deposito" in str(call.args[0])
        ]
        assert executed_sql, "No query against stock_por_deposito was executed"
        assert all(f"stock < {STOCK_SENTINEL}" in sql for sql in executed_sql), (
            "Capital query does not exclude the stock sentinel — capital will be inflated"
        )

    def test_kpis_nullable_fields_accept_none(self, user_con_permiso_kpis) -> None:
        """Nullable KPI fields (capital_*) can be null when no monetary data exists."""
        from app.core.database import get_async_db, get_db
        from app.main import app
        from starlette.testclient import TestClient

        null_row = MagicMock()
        null_row.total_productos = 0
        null_row.stock_total = 0
        null_row.capital_costo_ars = None
        null_row.capital_costo_usd = None
        null_row.capital_venta_ars = None
        null_row.capital_muerto_ars = None
        null_row.pct_capital_muerto = None

        result = MagicMock()
        result.fetchone.return_value = null_row

        mock_db = MagicMock()
        mock_db.execute.return_value = result

        def _override_get_db():
            yield mock_db

        async def _override_get_async_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_async_db] = _override_get_async_db

        with TestClient(app, raise_server_exceptions=False) as c:
            with (
                _PATCH_TIENE_PERMISO_TRUE,
                _PATCH_OBTENER_PERMISOS,
                patch("app.routers.consultas._get_tc_venta", return_value=None),
            ):
                response = c.get(
                    "/api/consultas/ranking/kpis",
                    headers=_auth(user_con_permiso_kpis),
                )

        app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["total_productos"] == 0
        assert body["capital_costo_ars"] is None
        assert body["pct_capital_muerto"] is None
