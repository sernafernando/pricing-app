"""
Integration tests for consultas.ver_mi_ranking permission — scoped access.

Covers:
  1. Access control:
     - User with only consultas.ver_ranking → 200 (unchanged)
     - User with only consultas.ver_mi_ranking → 200
     - User with neither → 403

  2. SQL scoping inspection:
     - FULL user (ver_ranking) → executed SQL does NOT contain 'mp_scope.usuario_id'
     - SCOPED user (only ver_mi_ranking) → executed SQL DOES contain
       'mp_scope.usuario_id' EXISTS filter and binds scope_user_id = user.id

  Tests cover /ranking, /ranking/kpis, /ranking/resumen, /ranking/facets.

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
# Fixtures
# ---------------------------------------------------------------------------

SCOPED_USER_ID = 77


@pytest.fixture()
def rol_scope(db) -> Rol:
    """Role for scope tests."""
    rol = Rol(codigo="SCOPE_TEST", nombre="Scope Test", es_sistema=False, orden=30, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def user_full(db, rol_scope) -> Usuario:
    """User with consultas.ver_ranking (full access)."""
    user = Usuario(
        username="full_access_user",
        email="full_access@example.com",
        nombre="Full Access User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_scope.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def user_scoped(db, rol_scope) -> Usuario:
    """User with ONLY consultas.ver_mi_ranking (scoped access).

    We forcibly set id=SCOPED_USER_ID to make SQL assertions deterministic.
    """
    user = Usuario(
        username="scoped_user",
        email="scoped@example.com",
        nombre="Scoped User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_scope.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    # Override id to a known value so we can assert scope_user_id in SQL params
    user.id = SCOPED_USER_ID
    return user


@pytest.fixture()
def user_no_perm(db, rol_scope) -> Usuario:
    """User with neither ranking permission."""
    user = Usuario(
        username="no_perm_scope_user",
        email="noperm_scope@example.com",
        nombre="NoPerm Scope User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_scope.id,
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


# ---------------------------------------------------------------------------
# Mock DB factory
# ---------------------------------------------------------------------------


def _make_mock_db() -> MagicMock:
    """Mock DB session that records all execute() calls.

    Returns a flexible result that supports both fetchall() and fetchone(),
    so it works for ranking (2 queries), kpis (1 query), resumen (2 queries),
    and facets (4 queries), all without hitting a real DB.
    """
    # KPIs fetchone row needs named attributes
    kpis_row = MagicMock()
    kpis_row.total_productos = 0
    kpis_row.stock_total = 0
    kpis_row.capital_costo_ars = None
    kpis_row.capital_costo_usd = None
    kpis_row.capital_venta_ars = None
    kpis_row.capital_muerto_ars = None
    kpis_row.pct_capital_muerto = None

    # resumen totales fetchone row needs named attributes
    totales_row = MagicMock()
    totales_row.num_productos = 0
    totales_row.stock_total = 0
    totales_row.valor_costo_ars = None
    totales_row.valor_costo_usd = None
    totales_row.valor_venta = None

    # tc_venta fetchone (tipo_cambio)
    tc_row = None  # _get_tc_venta returns None when row is None → fine

    def _make_result(idx: int) -> MagicMock:
        r = MagicMock()
        r.fetchall.return_value = []
        # fetchone: vary by call index to handle different endpoints
        # call 0 = tc_venta (None row is ok), others need a valid row
        if idx == 0:
            r.fetchone.return_value = tc_row
        elif idx == 1:
            # Could be kpis main row or ranking count or resumen totales
            r.fetchone.return_value = kpis_row
        else:
            r.fetchone.return_value = totales_row
        return r

    call_count = {"n": 0}

    def _execute(stmt, params=None):
        idx = call_count["n"]
        call_count["n"] += 1
        return _make_result(idx)

    mock_db = MagicMock()
    mock_db.execute.side_effect = _execute
    return mock_db


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------

# For full-access users: tiene_permiso always True (has ver_ranking)
_PATCH_FULL_PERMISO = patch(
    "app.services.permisos_service.PermisosService.tiene_permiso",
    return_value=True,
)
_PATCH_FULL_OBTENER = patch(
    "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
    return_value={"consultas.ver_ranking"},
)
# tiene_algun_permiso returns True so require_algun_permiso passes
_PATCH_ALGUN_TRUE = patch(
    "app.services.permisos_service.PermisosService.tiene_algun_permiso",
    return_value=True,
)

# For scoped users: tiene_permiso returns False for ver_ranking, but tiene_algun_permiso True
_PATCH_SCOPED_TIENE = patch(
    "app.services.permisos_service.PermisosService.tiene_permiso",
    return_value=False,
)
_PATCH_SCOPED_OBTENER = patch(
    "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
    return_value={"consultas.ver_mi_ranking"},
)

# For no-perm users
_PATCH_NO_PERM_TIENE = patch(
    "app.services.permisos_service.PermisosService.tiene_permiso",
    return_value=False,
)
_PATCH_NO_PERM_ALGUN = patch(
    "app.services.permisos_service.PermisosService.tiene_algun_permiso",
    return_value=False,
)
_PATCH_NO_PERM_OBTENER = patch(
    "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
    return_value=set(),
)


# ---------------------------------------------------------------------------
# Fixtures: clients with mock DB
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_full(user_full):
    """TestClient with full-access user and mock DB."""
    from app.core.database import get_async_db, get_db
    from app.main import app

    mock_db = _make_mock_db()

    def _get_db():
        yield mock_db

    async def _get_async_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_async_db] = _get_async_db

    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c, user_full, mock_db

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_async_db, None)


@pytest.fixture()
def client_scoped(user_scoped):
    """TestClient with scoped user and mock DB."""
    from app.core.database import get_async_db, get_db
    from app.main import app

    mock_db = _make_mock_db()

    def _get_db():
        yield mock_db

    async def _get_async_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_async_db] = _get_async_db

    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c, user_scoped, mock_db

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_async_db, None)


@pytest.fixture()
def client_no_perm(user_no_perm):
    """TestClient with no-perm user (uses real SQLite DB)."""
    # No mock DB needed — we expect 403 before any query
    yield None, user_no_perm


# ---------------------------------------------------------------------------
# 1. Access control tests
# ---------------------------------------------------------------------------


class TestRankingScopedAccess:
    """Permission gate: ver_ranking, ver_mi_ranking, neither."""

    def test_full_user_ranking_200(self, client_full) -> None:
        """User with ver_ranking → 200."""
        client, user, _ = client_full
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            response = client.get("/api/consultas/ranking", headers=_auth(user))
        assert response.status_code == 200

    def test_scoped_user_ranking_200(self, client_scoped) -> None:
        """User with ONLY ver_mi_ranking → 200."""
        client, user, _ = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            response = client.get("/api/consultas/ranking", headers=_auth(user))
        assert response.status_code == 200

    def test_no_perm_user_ranking_403(self, client, user_no_perm) -> None:
        """User with neither permission → 403."""
        with _PATCH_NO_PERM_TIENE, _PATCH_NO_PERM_ALGUN, _PATCH_NO_PERM_OBTENER:
            response = client.get("/api/consultas/ranking", headers=_auth(user_no_perm))
        assert response.status_code == 403

    def test_full_user_kpis_200(self, client_full) -> None:
        """User with ver_ranking → kpis 200."""
        client, user, _ = client_full
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            response = client.get("/api/consultas/ranking/kpis", headers=_auth(user))
        assert response.status_code == 200

    def test_scoped_user_kpis_200(self, client_scoped) -> None:
        """User with ONLY ver_mi_ranking → kpis 200."""
        client, user, _ = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            response = client.get("/api/consultas/ranking/kpis", headers=_auth(user))
        assert response.status_code == 200

    def test_no_perm_user_kpis_403(self, client, user_no_perm) -> None:
        """User with neither → kpis 403."""
        with _PATCH_NO_PERM_TIENE, _PATCH_NO_PERM_ALGUN, _PATCH_NO_PERM_OBTENER:
            response = client.get("/api/consultas/ranking/kpis", headers=_auth(user_no_perm))
        assert response.status_code == 403

    def test_full_user_resumen_200(self, client_full) -> None:
        """User with ver_ranking → resumen 200."""
        client, user, _ = client_full
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            response = client.get("/api/consultas/ranking/resumen", headers=_auth(user))
        assert response.status_code == 200

    def test_scoped_user_resumen_200(self, client_scoped) -> None:
        """User with ONLY ver_mi_ranking → resumen 200."""
        client, user, _ = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            response = client.get("/api/consultas/ranking/resumen", headers=_auth(user))
        assert response.status_code == 200

    def test_no_perm_user_resumen_403(self, client, user_no_perm) -> None:
        """User with neither → resumen 403."""
        with _PATCH_NO_PERM_TIENE, _PATCH_NO_PERM_ALGUN, _PATCH_NO_PERM_OBTENER:
            response = client.get("/api/consultas/ranking/resumen", headers=_auth(user_no_perm))
        assert response.status_code == 403

    def test_full_user_facets_200(self, client_full) -> None:
        """User with ver_ranking → facets 200."""
        client, user, _ = client_full
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            response = client.get("/api/consultas/ranking/facets", headers=_auth(user))
        assert response.status_code == 200

    def test_scoped_user_facets_200(self, client_scoped) -> None:
        """User with ONLY ver_mi_ranking → facets 200."""
        client, user, _ = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            response = client.get("/api/consultas/ranking/facets", headers=_auth(user))
        assert response.status_code == 200

    def test_no_perm_user_facets_403(self, client, user_no_perm) -> None:
        """User with neither → facets 403."""
        with _PATCH_NO_PERM_TIENE, _PATCH_NO_PERM_ALGUN, _PATCH_NO_PERM_OBTENER:
            response = client.get("/api/consultas/ranking/facets", headers=_auth(user_no_perm))
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# 2. SQL scoping inspection
# ---------------------------------------------------------------------------


def _get_all_executed_sql(mock_db: MagicMock) -> list[str]:
    """Extract all SQL strings passed to mock_db.execute()."""
    sqls = []
    for c in mock_db.execute.call_args_list:
        args = c.args
        if args:
            stmt = args[0]
            sqls.append(str(stmt))
    return sqls


def _get_all_executed_params(mock_db: MagicMock) -> list[dict]:
    """Extract all params dicts passed to mock_db.execute()."""
    params_list = []
    for c in mock_db.execute.call_args_list:
        args = c.args
        kw = c.kwargs
        if len(args) >= 2:
            params_list.append(args[1])
        elif "params" in kw:
            params_list.append(kw["params"])
    return params_list


class TestRankingSQLScoping:
    """Inspect executed SQL to verify scope filter is applied correctly."""

    def test_full_user_ranking_sql_no_scope(self, client_full) -> None:
        """FULL user ranking SQL must NOT contain mp_scope.usuario_id."""
        client, user, mock_db = client_full
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking", headers=_auth(user))
        sqls = _get_all_executed_sql(mock_db)
        assert sqls, "Expected at least one SQL call"
        combined = " ".join(sqls)
        assert "mp_scope.usuario_id" not in combined

    def test_scoped_user_ranking_sql_has_scope(self, client_scoped) -> None:
        """SCOPED user ranking SQL must contain EXISTS mp_scope.usuario_id filter."""
        client, user, mock_db = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking", headers=_auth(user))
        sqls = _get_all_executed_sql(mock_db)
        combined = " ".join(sqls)
        assert "mp_scope.usuario_id" in combined, (
            f"Expected 'mp_scope.usuario_id' in ranking SQL for scoped user. Got: {combined[:500]}"
        )

    def test_scoped_user_ranking_binds_scope_user_id(self, client_scoped) -> None:
        """SCOPED user ranking must bind scope_user_id = user.id in params."""
        client, user, mock_db = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking", headers=_auth(user))
        all_params = _get_all_executed_params(mock_db)
        # At least one params dict must contain scope_user_id == user.id
        has_scope_param = any(isinstance(p, dict) and "scope_user_id" in p for p in all_params)
        assert has_scope_param, f"Expected 'scope_user_id' key in params. Got: {all_params}"

    def test_full_user_kpis_sql_no_scope(self, client_full) -> None:
        """FULL user kpis SQL must NOT contain mp_scope.usuario_id."""
        client, user, mock_db = client_full
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/kpis", headers=_auth(user))
        sqls = _get_all_executed_sql(mock_db)
        combined = " ".join(sqls)
        assert "mp_scope.usuario_id" not in combined

    def test_scoped_user_kpis_sql_has_scope(self, client_scoped) -> None:
        """SCOPED user kpis SQL must contain EXISTS mp_scope.usuario_id."""
        client, user, mock_db = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/kpis", headers=_auth(user))
        sqls = _get_all_executed_sql(mock_db)
        combined = " ".join(sqls)
        assert "mp_scope.usuario_id" in combined

    def test_scoped_user_kpis_binds_scope_user_id(self, client_scoped) -> None:
        """SCOPED user kpis must bind scope_user_id."""
        client, user, mock_db = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/kpis", headers=_auth(user))
        all_params = _get_all_executed_params(mock_db)
        has_scope_param = any(isinstance(p, dict) and "scope_user_id" in p for p in all_params)
        assert has_scope_param

    def test_full_user_resumen_sql_no_scope(self, client_full) -> None:
        """FULL user resumen SQL must NOT contain mp_scope.usuario_id."""
        client, user, mock_db = client_full
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/resumen", headers=_auth(user))
        sqls = _get_all_executed_sql(mock_db)
        combined = " ".join(sqls)
        assert "mp_scope.usuario_id" not in combined

    def test_scoped_user_resumen_sql_has_scope(self, client_scoped) -> None:
        """SCOPED user resumen SQL must contain EXISTS mp_scope.usuario_id."""
        client, user, mock_db = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/resumen", headers=_auth(user))
        sqls = _get_all_executed_sql(mock_db)
        combined = " ".join(sqls)
        assert "mp_scope.usuario_id" in combined

    def test_scoped_user_resumen_binds_scope_user_id(self, client_scoped) -> None:
        """SCOPED user resumen must bind scope_user_id."""
        client, user, mock_db = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/resumen", headers=_auth(user))
        all_params = _get_all_executed_params(mock_db)
        has_scope_param = any(isinstance(p, dict) and "scope_user_id" in p for p in all_params)
        assert has_scope_param

    def test_full_user_facets_sql_no_scope(self, client_full) -> None:
        """FULL user facets SQL must NOT contain mp_scope.usuario_id."""
        client, user, mock_db = client_full
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/facets", headers=_auth(user))
        sqls = _get_all_executed_sql(mock_db)
        combined = " ".join(sqls)
        assert "mp_scope.usuario_id" not in combined

    def test_scoped_user_facets_sql_has_scope(self, client_scoped) -> None:
        """SCOPED user facets SQL must contain mp_scope.usuario_id."""
        client, user, mock_db = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/facets", headers=_auth(user))
        sqls = _get_all_executed_sql(mock_db)
        combined = " ".join(sqls)
        assert "mp_scope.usuario_id" in combined

    def test_scoped_user_facets_binds_scope_user_id(self, client_scoped) -> None:
        """SCOPED user facets must bind scope_user_id."""
        client, user, mock_db = client_scoped
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/facets", headers=_auth(user))
        all_params = _get_all_executed_params(mock_db)
        has_scope_param = any(isinstance(p, dict) and "scope_user_id" in p for p in all_params)
        assert has_scope_param
