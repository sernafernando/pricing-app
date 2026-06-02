"""
Tests for two consultas ranking fixes:

Fix 1: dias_sin_venta NULL → sorts NULLS FIRST on DESC (most aged), NULLS LAST on ASC.
  - _build_nulls_clause('dias_sin_venta', 'desc') → 'NULLS FIRST'
  - _build_nulls_clause('dias_sin_venta', 'asc')  → 'NULLS LAST'
  - _build_nulls_clause('valor_costo_ars', 'desc') → 'NULLS LAST' (unchanged)
  - _build_nulls_clause('valor_costo_ars', 'asc')  → 'NULLS LAST' (unchanged)

Fix 2: /ranking/facets cross-filtering.
  - ?marca=X → categorias SQL contains 'pe.marca = :marca', marcas SQL does NOT.
  - ?pm=Y    → marcas + categorias SQL include pm join/clause; pms SQL does NOT.
  - ?pm=sin_pm → uses 'mp.usuario_id IS NULL'; pms SQL does NOT filter by pm.
  - No params → existing behavior unchanged (all values returned, no extra filters).

Tests use mock DB (SQL inspection) to avoid PostgreSQL-specific SQL not supported by SQLite.
No @pytest.mark.asyncio — plain def tests via TestClient.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.models.rol import Rol
from app.routers.consultas import _build_nulls_clause


# ---------------------------------------------------------------------------
# Fix 1: Unit tests for _build_nulls_clause
# ---------------------------------------------------------------------------


class TestBuildNullsClause:
    """dias_sin_venta NULL = most-aged = should sort NULLS FIRST on DESC."""

    def test_dias_sin_venta_desc_is_nulls_first(self) -> None:
        """NULL means never-sold → infinitely aged → top of DESC sort."""
        result = _build_nulls_clause("dias_sin_venta", "desc")
        assert result == "NULLS FIRST"

    def test_dias_sin_venta_asc_is_nulls_last(self) -> None:
        """Ascending sort: never-sold products go to bottom (largest value last)."""
        result = _build_nulls_clause("dias_sin_venta", "asc")
        assert result == "NULLS LAST"

    def test_valor_costo_ars_desc_still_nulls_last(self) -> None:
        """Products without cost data should NOT float to top — NULLS LAST regardless."""
        result = _build_nulls_clause("valor_costo_ars", "desc")
        assert result == "NULLS LAST"

    def test_valor_costo_ars_asc_still_nulls_last(self) -> None:
        result = _build_nulls_clause("valor_costo_ars", "asc")
        assert result == "NULLS LAST"

    def test_last_purchase_date_desc_nulls_last(self) -> None:
        """last_purchase_date stays in _NULLS_LAST_COLS — unchanged."""
        result = _build_nulls_clause("last_purchase_date", "desc")
        assert result == "NULLS LAST"

    def test_last_purchase_date_asc_nulls_last(self) -> None:
        result = _build_nulls_clause("last_purchase_date", "asc")
        assert result == "NULLS LAST"


# ---------------------------------------------------------------------------
# Fix 2: Integration tests for /ranking/facets cross-filtering
# ---------------------------------------------------------------------------


@pytest.fixture()
def rol_facets(db) -> Rol:
    rol = Rol(codigo="FACETS_FIX", nombre="Facets Fix", es_sistema=False, orden=40, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def user_full_facets(db, rol_facets) -> Usuario:
    """User with full ver_ranking access."""
    user = Usuario(
        username="facets_fix_user",
        email="facets_fix@example.com",
        nombre="Facets Fix User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_facets.id,
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


_PATCH_FULL_PERMISO = patch(
    "app.services.permisos_service.PermisosService.tiene_permiso",
    return_value=True,
)
_PATCH_FULL_OBTENER = patch(
    "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
    return_value={"consultas.ver_ranking"},
)
_PATCH_ALGUN_TRUE = patch(
    "app.services.permisos_service.PermisosService.tiene_algun_permiso",
    return_value=True,
)


def _make_mock_db() -> MagicMock:
    """Mock DB session that records all execute() calls and returns empty results."""

    def _make_result() -> MagicMock:
        r = MagicMock()
        r.fetchall.return_value = []
        r.fetchone.return_value = None
        return r

    mock_db = MagicMock()
    mock_db.execute.side_effect = lambda stmt, params=None: _make_result()
    return mock_db


def _get_all_executed_calls(mock_db: MagicMock) -> list[tuple[str, dict]]:
    """Return list of (sql_text, params_dict) for every db.execute() call."""
    results = []
    for call in mock_db.execute.call_args_list:
        args, kwargs = call
        stmt = args[0] if args else kwargs.get("statement", "")
        params = args[1] if len(args) > 1 else kwargs.get("parameters", {}) or {}
        results.append((str(stmt), params or {}))
    return results


@pytest.fixture()
def client_full_facets(user_full_facets):
    """TestClient with full-access user and mock DB."""
    from app.core.database import get_async_db, get_db
    from app.main import app
    from fastapi.testclient import TestClient

    mock_db = _make_mock_db()

    def _get_db():
        yield mock_db

    async def _get_async_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_async_db] = _get_async_db

    with TestClient(app) as c:
        yield c, user_full_facets, mock_db

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_async_db, None)


class TestFacetsCrossFilter:
    """Cross-filtering: each facet filters by the OTHER dimensions, not its own."""

    def test_no_params_no_cross_filter_sql(self, client_full_facets) -> None:
        """No params → SQL has no marca/categoria/pm filter clauses."""
        client, user, mock_db = client_full_facets
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            response = client.get("/api/consultas/ranking/facets", headers=_auth(user))
        assert response.status_code == 200
        calls = _get_all_executed_calls(mock_db)
        # Should not inject any filter params when none requested
        all_params = {k: v for _, p in calls for k, v in p.items()}
        assert "marca" not in all_params
        assert "categoria" not in all_params
        assert "pm_nombre" not in all_params

    def test_marca_filter_categorias_sql_has_marca(self, client_full_facets) -> None:
        """?marca=X → categorias query SQL must filter by pe.marca = :marca."""
        client, user, mock_db = client_full_facets
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            response = client.get(
                "/api/consultas/ranking/facets?marca=ACME",
                headers=_auth(user),
            )
        assert response.status_code == 200
        calls = _get_all_executed_calls(mock_db)
        # At least one categorias query should contain pe.marca = :marca
        cat_calls_with_marca = [
            sql
            for sql, params in calls
            if "categoria" in sql.lower() and "pe.marca" in sql and params.get("marca") == "ACME"
        ]
        assert cat_calls_with_marca, "categorias query must filter by marca when ?marca= is given"

    def test_marca_filter_marcas_sql_excludes_self(self, client_full_facets) -> None:
        """?marca=X → the marcas facet params must NOT include 'marca' (self-exclusion)."""
        client, user, mock_db = client_full_facets
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/facets?marca=ACME", headers=_auth(user))
        calls = _get_all_executed_calls(mock_db)
        # The marcas query is the one whose params do NOT include 'marca' as a filter key.
        # We verify this by finding calls with 'distinct' + 'pe.marca' in the SELECT clause.
        # Strategy: the marcas SQL selects "pe.marca" but its params must not contain "marca".
        marcas_calls = [
            (sql, params)
            for sql, params in calls
            if "select distinct pe.marca" in sql.lower().replace("\n", " ").replace("  ", " ")
        ]
        assert marcas_calls, "Expected at least one SQL call selecting DISTINCT pe.marca"
        for _, params in marcas_calls:
            assert "marca" not in params, (
                f"marcas query params must not include 'marca' (self-exclusion), got params: {params}"
            )

    def test_pm_filter_marcas_sql_has_pm_clause(self, client_full_facets) -> None:
        """?pm=SomePM → marcas query must include a pm join/clause."""
        client, user, mock_db = client_full_facets
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/facets?pm=Fernando", headers=_auth(user))
        calls = _get_all_executed_calls(mock_db)
        # At least one marcas query must bind pm_nombre=Fernando
        pm_in_params = any(params.get("pm_nombre") == "Fernando" for _, params in calls)
        assert pm_in_params, "pm=Fernando must bind pm_nombre in at least one facet query"

    def test_pm_filter_pms_sql_excludes_self(self, client_full_facets) -> None:
        """?pm=SomePM → pms query itself must NOT filter by pm."""
        client, user, mock_db = client_full_facets
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/facets?pm=Fernando", headers=_auth(user))
        calls = _get_all_executed_calls(mock_db)
        # The pms query joins marcas_pm + usuarios — find it and check it has no pm_nombre param
        pms_calls = [
            (sql, params) for sql, params in calls if "marcas_pm" in sql and "usuarios" in sql and "u.nombre" in sql
        ]
        for sql, params in pms_calls:
            assert "pm_nombre" not in params, (
                f"pms query must not self-filter by pm, found pm_nombre in params: {params}"
            )

    def test_pm_sin_pm_uses_null_check(self, client_full_facets) -> None:
        """?pm=sin_pm → at least one query must use 'mp.usuario_id IS NULL'."""
        client, user, mock_db = client_full_facets
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/facets?pm=sin_pm", headers=_auth(user))
        calls = _get_all_executed_calls(mock_db)
        combined_sql = " ".join(sql for sql, _ in calls)
        assert "mp.usuario_id IS NULL" in combined_sql or "usuario_id IS NULL" in combined_sql, (
            "pm=sin_pm must produce a IS NULL check in at least one query"
        )

    def test_pm_sin_pm_pms_query_no_null_filter(self, client_full_facets) -> None:
        """?pm=sin_pm → the pms list itself must NOT self-filter by pm=sin_pm."""
        client, user, mock_db = client_full_facets
        with _PATCH_FULL_PERMISO, _PATCH_FULL_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/facets?pm=sin_pm", headers=_auth(user))
        calls = _get_all_executed_calls(mock_db)
        # pms query selects u.nombre from marcas_pm + usuarios
        pms_calls = [(sql, params) for sql, params in calls if "marcas_pm" in sql and "u.nombre" in sql]
        for sql, params in pms_calls:
            # pms query should not apply sin_pm NULL filter to itself
            # (that would hide all non-null PMs from the list)
            assert "pm_nombre" not in params
