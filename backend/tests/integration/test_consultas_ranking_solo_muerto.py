"""
Tests for the `solo_muerto` filter on consultas ranking endpoints.

Covers (SQL inspection — same pattern as test_kpis_sql_excludes_stock_sentinel):
  - /ranking?solo_muerto=true → SQL contains the NOT EXISTS dead-stock clause
  - /ranking?solo_muerto=false (default) → SQL does NOT contain it
  - count query also gets the clause when solo_muerto=true
  - /ranking/kpis?solo_muerto=true → SQL contains the clause
  - /ranking/kpis?solo_muerto=false → SQL does NOT contain it
  - /ranking/resumen?solo_muerto=true → SQL contains the clause
  - /ranking/resumen?solo_muerto=false → SQL does NOT contain it

No @pytest.mark.asyncio — all tests are synchronous (SQL inspection via MagicMock).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.models.rol import Rol


# ---------------------------------------------------------------------------
# Shared patch helpers
# ---------------------------------------------------------------------------

_PATCH_TIENE_PERMISO_TRUE = patch(
    "app.services.permisos_service.PermisosService.tiene_permiso",
    return_value=True,
)
_PATCH_OBTENER_PERMISOS = patch(
    "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
    return_value={"consultas.ver_ranking"},
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def rol_muerto(db) -> Rol:
    rol = Rol(codigo="MUERTO_TEST", nombre="Muerto Test", es_sistema=False, orden=30, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def user_muerto(db, rol_muerto) -> Usuario:
    user = Usuario(
        username="muerto_user",
        email="muerto@example.com",
        nombre="Muerto User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_muerto.id,
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
# Mock DB builders
# ---------------------------------------------------------------------------


def _make_ranking_mock_db() -> MagicMock:
    """Mock DB for the /ranking endpoint.

    /ranking calls db.execute twice (data query + count query).
    """
    items_result = MagicMock()
    items_result.fetchall.return_value = []

    count_row = MagicMock()
    count_row.__getitem__ = lambda self, _: 0

    count_result = MagicMock()
    count_result.fetchone.return_value = count_row

    mock_db = MagicMock()
    # First call → data query (fetchall), second call → count query (fetchone).
    mock_db.execute.side_effect = [items_result, count_result]
    return mock_db


def _make_single_row_mock_db(row: MagicMock) -> MagicMock:
    """Mock DB for endpoints that execute a single query returning one row."""
    result = MagicMock()
    result.fetchone.return_value = row

    mock_db = MagicMock()
    mock_db.execute.return_value = result
    return mock_db


def _kpis_row() -> MagicMock:
    row = MagicMock()
    row.total_productos = 0
    row.stock_total = 0
    row.capital_costo_ars = None
    row.capital_costo_usd = None
    row.capital_venta_ars = None
    row.capital_muerto_ars = None
    row.pct_capital_muerto = None
    return row


def _resumen_rows_and_totals() -> tuple[MagicMock, MagicMock]:
    """Returns (rows_result, totales_result) for resumen mock."""
    rows_result = MagicMock()
    rows_result.fetchall.return_value = []

    totales_row = MagicMock()
    totales_row.num_productos = 0
    totales_row.stock_total = 0
    totales_row.valor_costo_ars = None
    totales_row.valor_costo_usd = None
    totales_row.valor_venta = None

    totales_result = MagicMock()
    totales_result.fetchone.return_value = totales_row

    return rows_result, totales_result


# ---------------------------------------------------------------------------
# Constant to assert (must match what the router will generate)
# ---------------------------------------------------------------------------

_DEAD_STOCK_CLAUSE = "tct_m.ct_date >= NOW()::date - INTERVAL '365 days'"


# ---------------------------------------------------------------------------
# Helper: collect all SQL strings executed against the mock DB
# ---------------------------------------------------------------------------


def _all_sql(mock_db: MagicMock) -> list[str]:
    return [str(c.args[0]) for c in mock_db.execute.call_args_list if c.args]


# ---------------------------------------------------------------------------
# /ranking
# ---------------------------------------------------------------------------


class TestRankingSoloMuerto:
    """solo_muerto filter on GET /ranking."""

    def _client_with_mock(self, mock_db: MagicMock):
        from app.core.database import get_async_db, get_db
        from app.main import app
        from starlette.testclient import TestClient

        def _override_get_db():
            yield mock_db

        async def _override_get_async_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_async_db] = _override_get_async_db
        return TestClient(app, raise_server_exceptions=False)

    def test_solo_muerto_true_injects_not_exists_clause_in_data_query(self, user_muerto):
        """solo_muerto=true → data query contains the NOT EXISTS dead-stock clause."""
        mock_db = _make_ranking_mock_db()
        client = self._client_with_mock(mock_db)

        try:
            with (
                _PATCH_TIENE_PERMISO_TRUE,
                _PATCH_OBTENER_PERMISOS,
                patch("app.routers.consultas._get_tc_venta", return_value=None),
            ):
                response = client.get(
                    "/api/consultas/ranking",
                    params={"solo_muerto": "true"},
                    headers=_auth(user_muerto),
                )
        finally:
            from app.main import app as _app

            _app.dependency_overrides.clear()

        assert response.status_code == 200
        sqls = _all_sql(mock_db)
        # The data query (first execute call) must contain the clause
        assert sqls, "No SQL was executed"
        data_sql = sqls[0]
        assert _DEAD_STOCK_CLAUSE in data_sql, (
            f"Dead-stock NOT EXISTS clause missing from data query.\nSQL:\n{data_sql}"
        )

    def test_solo_muerto_true_injects_not_exists_clause_in_count_query(self, user_muerto):
        """solo_muerto=true → count query ALSO contains the NOT EXISTS dead-stock clause."""
        mock_db = _make_ranking_mock_db()
        client = self._client_with_mock(mock_db)

        try:
            with (
                _PATCH_TIENE_PERMISO_TRUE,
                _PATCH_OBTENER_PERMISOS,
                patch("app.routers.consultas._get_tc_venta", return_value=None),
            ):
                client.get(
                    "/api/consultas/ranking",
                    params={"solo_muerto": "true"},
                    headers=_auth(user_muerto),
                )
        finally:
            from app.main import app as _app

            _app.dependency_overrides.clear()

        sqls = _all_sql(mock_db)
        assert len(sqls) >= 2, "Expected at least 2 execute calls (data + count)"
        count_sql = sqls[1]
        assert _DEAD_STOCK_CLAUSE in count_sql, (
            f"Dead-stock NOT EXISTS clause missing from count query.\nSQL:\n{count_sql}"
        )

    def test_solo_muerto_false_omits_clause_from_data_query(self, user_muerto):
        """solo_muerto=false (default) → data query does NOT contain the clause."""
        mock_db = _make_ranking_mock_db()
        client = self._client_with_mock(mock_db)

        try:
            with (
                _PATCH_TIENE_PERMISO_TRUE,
                _PATCH_OBTENER_PERMISOS,
                patch("app.routers.consultas._get_tc_venta", return_value=None),
            ):
                client.get(
                    "/api/consultas/ranking",
                    params={"solo_muerto": "false"},
                    headers=_auth(user_muerto),
                )
        finally:
            from app.main import app as _app

            _app.dependency_overrides.clear()

        sqls = _all_sql(mock_db)
        assert sqls
        for sql in sqls:
            assert _DEAD_STOCK_CLAUSE not in sql, "Dead-stock clause unexpectedly present when solo_muerto=false"

    def test_solo_muerto_default_omits_clause(self, user_muerto):
        """No solo_muerto param → default False → clause absent."""
        mock_db = _make_ranking_mock_db()
        client = self._client_with_mock(mock_db)

        try:
            with (
                _PATCH_TIENE_PERMISO_TRUE,
                _PATCH_OBTENER_PERMISOS,
                patch("app.routers.consultas._get_tc_venta", return_value=None),
            ):
                client.get(
                    "/api/consultas/ranking",
                    headers=_auth(user_muerto),
                )
        finally:
            from app.main import app as _app

            _app.dependency_overrides.clear()

        sqls = _all_sql(mock_db)
        assert sqls
        for sql in sqls:
            assert _DEAD_STOCK_CLAUSE not in sql


# ---------------------------------------------------------------------------
# /ranking/kpis
# ---------------------------------------------------------------------------


class TestKpisSoloMuerto:
    """solo_muerto filter on GET /ranking/kpis."""

    def _client_with_mock(self, mock_db: MagicMock):
        from app.core.database import get_async_db, get_db
        from app.main import app
        from starlette.testclient import TestClient

        def _override_get_db():
            yield mock_db

        async def _override_get_async_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_async_db] = _override_get_async_db
        return TestClient(app, raise_server_exceptions=False)

    def test_solo_muerto_true_injects_clause_in_kpis(self, user_muerto):
        """solo_muerto=true → kpis SQL contains the NOT EXISTS dead-stock clause."""
        mock_db = _make_single_row_mock_db(_kpis_row())
        client = self._client_with_mock(mock_db)

        try:
            with (
                _PATCH_TIENE_PERMISO_TRUE,
                _PATCH_OBTENER_PERMISOS,
                patch("app.routers.consultas._get_tc_venta", return_value=None),
            ):
                response = client.get(
                    "/api/consultas/ranking/kpis",
                    params={"solo_muerto": "true"},
                    headers=_auth(user_muerto),
                )
        finally:
            from app.main import app as _app

            _app.dependency_overrides.clear()

        assert response.status_code == 200
        sqls = _all_sql(mock_db)
        assert sqls
        kpis_sql = next((s for s in sqls if "stock_por_deposito" in s), None)
        assert kpis_sql is not None, "No KPI query found against stock_por_deposito"
        assert _DEAD_STOCK_CLAUSE in kpis_sql, f"Dead-stock clause missing from kpis SQL.\nSQL:\n{kpis_sql}"

    def test_solo_muerto_false_omits_clause_from_kpis(self, user_muerto):
        """solo_muerto=false → kpis SQL does NOT contain the dead-stock clause."""
        mock_db = _make_single_row_mock_db(_kpis_row())
        client = self._client_with_mock(mock_db)

        try:
            with (
                _PATCH_TIENE_PERMISO_TRUE,
                _PATCH_OBTENER_PERMISOS,
                patch("app.routers.consultas._get_tc_venta", return_value=None),
            ):
                client.get(
                    "/api/consultas/ranking/kpis",
                    params={"solo_muerto": "false"},
                    headers=_auth(user_muerto),
                )
        finally:
            from app.main import app as _app

            _app.dependency_overrides.clear()

        sqls = _all_sql(mock_db)
        assert sqls
        for sql in sqls:
            assert _DEAD_STOCK_CLAUSE not in sql


# ---------------------------------------------------------------------------
# /ranking/resumen
# ---------------------------------------------------------------------------


class TestResumenSoloMuerto:
    """solo_muerto filter on GET /ranking/resumen."""

    def _client_with_mock(self, mock_db: MagicMock):
        from app.core.database import get_async_db, get_db
        from app.main import app
        from starlette.testclient import TestClient

        def _override_get_db():
            yield mock_db

        async def _override_get_async_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_async_db] = _override_get_async_db
        return TestClient(app, raise_server_exceptions=False)

    def _make_resumen_mock_db(self) -> MagicMock:
        rows_result, totales_result = _resumen_rows_and_totals()
        mock_db = MagicMock()
        mock_db.execute.side_effect = [rows_result, totales_result]
        return mock_db

    def test_solo_muerto_true_injects_clause_in_resumen(self, user_muerto):
        """solo_muerto=true → resumen SQL contains the NOT EXISTS dead-stock clause."""
        mock_db = self._make_resumen_mock_db()
        client = self._client_with_mock(mock_db)

        try:
            with (
                _PATCH_TIENE_PERMISO_TRUE,
                _PATCH_OBTENER_PERMISOS,
                patch("app.routers.consultas._get_tc_venta", return_value=None),
            ):
                response = client.get(
                    "/api/consultas/ranking/resumen",
                    params={"solo_muerto": "true"},
                    headers=_auth(user_muerto),
                )
        finally:
            from app.main import app as _app

            _app.dependency_overrides.clear()

        assert response.status_code == 200
        sqls = _all_sql(mock_db)
        assert sqls
        assert any(_DEAD_STOCK_CLAUSE in sql for sql in sqls), (
            f"Dead-stock clause missing from resumen SQLs.\nSQLs:\n{chr(10).join(sqls)}"
        )

    def test_solo_muerto_false_omits_clause_from_resumen(self, user_muerto):
        """solo_muerto=false → resumen SQL does NOT contain the dead-stock clause."""
        mock_db = self._make_resumen_mock_db()
        client = self._client_with_mock(mock_db)

        try:
            with (
                _PATCH_TIENE_PERMISO_TRUE,
                _PATCH_OBTENER_PERMISOS,
                patch("app.routers.consultas._get_tc_venta", return_value=None),
            ):
                client.get(
                    "/api/consultas/ranking/resumen",
                    params={"solo_muerto": "false"},
                    headers=_auth(user_muerto),
                )
        finally:
            from app.main import app as _app

            _app.dependency_overrides.clear()

        sqls = _all_sql(mock_db)
        assert sqls
        for sql in sqls:
            assert _DEAD_STOCK_CLAUSE not in sql
