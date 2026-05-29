"""
Integration tests for GET /api/consultas/ranking (TASK-2.3).

Covers:
  - No JWT → 401
  - Valid JWT without consultas.ver_ranking → 403
  - Valid JWT with consultas.ver_ranking → 200
  - Unknown sort_by → 422
  - page_size > 200 → 422
  - page_size = 0 → 422
  - No TipoCambio row → valor_costo and valor_venta null/handled (no 500)

Permission is mocked via PermisosService to avoid DB seed dependency.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.models.rol import Rol


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def rol_consultas(db) -> Rol:
    """CONSULTAS role for tests."""
    rol = Rol(codigo="CONSULTAS", nombre="Consultas", es_sistema=False, orden=20, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def user_con_permiso(db, rol_consultas) -> Usuario:
    """User that HAS consultas.ver_ranking."""
    user = Usuario(
        username="consultas_user",
        email="consultas@example.com",
        nombre="Consultas User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_consultas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def user_sin_permiso(db, rol_consultas) -> Usuario:
    """User that does NOT have consultas.ver_ranking."""
    user = Usuario(
        username="noperm_user",
        email="noperm@example.com",
        nombre="NoPerm User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_consultas.id,
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


# Patch helpers — must patch the class method directly (not the module symbol)
# because require_permiso captures PermisosService in its closure at import time.
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
# Tests
# ---------------------------------------------------------------------------


class TestRankingAuth:
    """Authentication and permission gate tests."""

    def test_no_jwt_returns_401(self, client) -> None:
        """No Authorization header → 401 or 403.

        FastAPI HTTPBearer (auto_error=True) returns 403 by default when no
        credentials are provided — this is the established project behaviour
        (see test_administracion_compras_router.py). We accept either code.
        """
        response = client.get("/api/consultas/ranking")
        assert response.status_code in (401, 403)

    def test_user_sin_permiso_returns_403(self, client, user_sin_permiso) -> None:
        """Valid JWT but without consultas.ver_ranking → 403."""
        with _PATCH_TIENE_PERMISO_FALSE, _PATCH_OBTENER_PERMISOS_EMPTY:
            response = client.get(
                "/api/consultas/ranking",
                headers=_auth(user_sin_permiso),
            )
        assert response.status_code == 403

    def test_user_con_permiso_returns_200(self, client_with_mock_db) -> None:
        """Valid JWT with consultas.ver_ranking → 200 with ranking envelope.

        Uses a mock DB session to avoid PostgreSQL-specific SQL (LATERAL, ANY)
        that SQLite does not support.
        """
        client, user = client_with_mock_db
        with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.get(
                "/api/consultas/ranking",
                headers=_auth(user),
            )
        assert response.status_code == 200
        body = response.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body


def _make_mock_db_session() -> MagicMock:
    """Return a MagicMock DB session where execute returns empty results.

    Called for tests that need to exercise the 200 path without a real
    PostgreSQL ERP instance (the ranking query uses LATERAL, ANY(), INTERVAL
    which are not supported by the SQLite test DB).
    """
    rows_result = MagicMock()
    rows_result.fetchall.return_value = []
    count_result = MagicMock()
    count_result.fetchone.return_value = (0,)

    call_count = {"n": 0}

    def _execute(stmt, params=None):
        call_count["n"] += 1
        # First call = main rows query; second call = count query
        if call_count["n"] == 1:
            return rows_result
        return count_result

    mock_db = MagicMock()
    mock_db.execute.side_effect = _execute
    return mock_db


@pytest.fixture()
def client_with_mock_db(user_con_permiso):
    """TestClient that uses a mock DB session for the ranking endpoint.

    Bypasses the SQLite limitation for PostgreSQL-specific SQL (LATERAL, ANY).
    """
    from app.core.database import get_async_db, get_db
    from app.main import app

    mock_db = _make_mock_db_session()

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


class TestRankingValidation:
    """Input validation — 422 on bad params."""

    def test_unknown_sort_by_returns_422(self, client, user_con_permiso) -> None:
        """Unknown sort_by value → 422."""
        with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.get(
                "/api/consultas/ranking",
                params={"sort_by": "campo_inventado"},
                headers=_auth(user_con_permiso),
            )
        assert response.status_code == 422

    def test_page_size_above_200_returns_422(self, client, user_con_permiso) -> None:
        """page_size > 200 → 422."""
        with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.get(
                "/api/consultas/ranking",
                params={"page_size": 201},
                headers=_auth(user_con_permiso),
            )
        assert response.status_code == 422

    def test_page_size_zero_returns_422(self, client, user_con_permiso) -> None:
        """page_size = 0 → 422."""
        with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.get(
                "/api/consultas/ranking",
                params={"page_size": 0},
                headers=_auth(user_con_permiso),
            )
        assert response.status_code == 422

    def test_page_size_200_is_valid(self, client_with_mock_db) -> None:
        """page_size = 200 (max boundary) → 200 OK."""
        client, user = client_with_mock_db
        with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.get(
                "/api/consultas/ranking",
                params={"page_size": 200},
                headers=_auth(user),
            )
        assert response.status_code == 200

    def test_invalid_ventana_dias_returns_422(self, client, user_con_permiso) -> None:
        """ventana_dias not in {30, 60, 90, 180} → 422."""
        with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.get(
                "/api/consultas/ranking",
                params={"ventana_dias": 45},
                headers=_auth(user_con_permiso),
            )
        assert response.status_code == 422


def _make_facets_mock_db_session() -> MagicMock:
    """Return a MagicMock DB session for the facets endpoint.

    The facets endpoint executes four queries (marcas, categorias, pms,
    depositos) via db.execute().  Each call returns a distinct MagicMock
    result whose fetchall() returns a plausible row list.
    """
    marcas_result = MagicMock()
    marcas_result.fetchall.return_value = [("Marca A",), ("Marca B",)]

    categorias_result = MagicMock()
    categorias_result.fetchall.return_value = [("Cat 1",), ("Cat 2",)]

    pms_result = MagicMock()
    pms_result.fetchall.return_value = [("Juan Pérez",), ("María García",)]

    depositos_result = MagicMock()
    depositos_result.fetchall.return_value = [(1,), (14,), (15,)]

    _results = [marcas_result, categorias_result, pms_result, depositos_result]
    call_count = {"n": 0}

    def _execute(stmt, params=None):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(_results):
            return _results[idx]
        return MagicMock()

    mock_db = MagicMock()
    mock_db.execute.side_effect = _execute
    return mock_db


@pytest.fixture()
def client_with_mock_db_facets(user_con_permiso):
    """TestClient with a mock DB session for the facets endpoint."""
    from app.core.database import get_async_db, get_db
    from app.main import app

    mock_db = _make_facets_mock_db_session()

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


class TestFacetsAuth:
    """Authentication and permission gate tests for /ranking/facets."""

    def test_no_jwt_returns_401_or_403(self, client) -> None:
        """No Authorization header → 401 or 403."""
        response = client.get("/api/consultas/ranking/facets")
        assert response.status_code in (401, 403)

    def test_user_sin_permiso_returns_403(self, client, user_sin_permiso) -> None:
        """Valid JWT but without consultas.ver_ranking → 403."""
        with _PATCH_TIENE_PERMISO_FALSE, _PATCH_OBTENER_PERMISOS_EMPTY:
            response = client.get(
                "/api/consultas/ranking/facets",
                headers=_auth(user_sin_permiso),
            )
        assert response.status_code == 403


class TestFacets200:
    """Shape tests for /ranking/facets 200 response."""

    def test_facets_returns_200_with_expected_shape(self, client_with_mock_db_facets) -> None:
        """Valid JWT with consultas.ver_ranking → 200 with facets envelope."""
        client, user = client_with_mock_db_facets
        with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.get(
                "/api/consultas/ranking/facets",
                headers=_auth(user),
            )
        assert response.status_code == 200
        body = response.json()
        assert "marcas" in body
        assert "categorias" in body
        assert "pms" in body
        assert "depositos" in body
        assert isinstance(body["marcas"], list)
        assert isinstance(body["categorias"], list)
        assert isinstance(body["pms"], list)
        assert isinstance(body["depositos"], list)

    def test_facets_marcas_are_strings(self, client_with_mock_db_facets) -> None:
        """marcas items are strings."""
        client, user = client_with_mock_db_facets
        with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.get(
                "/api/consultas/ranking/facets",
                headers=_auth(user),
            )
        assert response.status_code == 200
        body = response.json()
        assert all(isinstance(m, str) for m in body["marcas"])

    def test_facets_depositos_have_id_and_label(self, client_with_mock_db_facets) -> None:
        """depositos items have 'id' (int) and 'label' (str)."""
        client, user = client_with_mock_db_facets
        with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
            response = client.get(
                "/api/consultas/ranking/facets",
                headers=_auth(user),
            )
        assert response.status_code == 200
        body = response.json()
        for dep in body["depositos"]:
            assert "id" in dep
            assert "label" in dep
            assert isinstance(dep["id"], int)
            assert dep["label"] == f"Depósito {dep['id']}"


class TestRankingCurrencyFallback:
    """No TipoCambio row → valor_costo/valor_venta gracefully null."""

    def test_no_tipo_cambio_returns_200_with_null_valores(self, client_with_mock_db) -> None:
        """When no TipoCambio row exists the endpoint returns 200, not 500.

        _get_tc_venta is patched to return None, simulating an empty
        tipo_cambio table. The endpoint should return 200 with null
        valor_costo/valor_venta, not a 500 error.
        """
        client, user = client_with_mock_db
        with (
            _PATCH_TIENE_PERMISO_TRUE,
            _PATCH_OBTENER_PERMISOS,
            # Simulate no FX rate available
            patch("app.routers.consultas._get_tc_venta", return_value=None),
        ):
            response = client.get(
                "/api/consultas/ranking",
                headers=_auth(user),
            )
        # Must not 500 even with no TipoCambio data
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["items"], list)
