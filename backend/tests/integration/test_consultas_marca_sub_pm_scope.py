"""sub-pm-scope-marcas PR1: consultas.py raw-SQL sites must include the
marca_sub_pm OR-EXISTS branch (via app.services.pm_scope.scope_exists_sql).

Mirrors the mock-DB SQL-capture convention from test_consultas_ranking_scope.py.
Covers the 4 endpoints touching the 5 EXISTS fragments, plus a check that the
PM-dropdown query stays titular-only in PR1 (see the `ponytail:` marker in
consultas.py — dropdown + pm-name filter unify over marca_sub_pm in PR2).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.models.rol import Rol

SCOPED_USER_ID = 88


@pytest.fixture()
def rol_sub_pm_scope(db) -> Rol:
    rol = Rol(codigo="SUB_PM_SCOPE_TEST", nombre="Sub PM Scope Test", es_sistema=False, orden=31, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def user_scoped_sub_pm(db, rol_sub_pm_scope) -> Usuario:
    user = Usuario(
        username="scoped_sub_pm_user",
        email="scoped_sub_pm@example.com",
        nombre="Scoped Sub PM User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_sub_pm_scope.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    user.id = SCOPED_USER_ID
    return user


def _token(user: Usuario) -> str:
    return create_access_token(data={"sub": user.username})


def _auth(user: Usuario) -> dict:
    return {"Authorization": f"Bearer {_token(user)}"}


def _make_mock_db() -> MagicMock:
    kpis_row = MagicMock()
    kpis_row.total_productos = 0
    kpis_row.stock_total = 0
    kpis_row.capital_costo_ars = None
    kpis_row.capital_costo_usd = None
    kpis_row.capital_venta_ars = None
    kpis_row.capital_muerto_ars = None
    kpis_row.pct_capital_muerto = None

    totales_row = MagicMock()
    totales_row.num_productos = 0
    totales_row.stock_total = 0
    totales_row.valor_costo_ars = None
    totales_row.valor_costo_usd = None
    totales_row.valor_venta = None

    def _make_result(idx: int) -> MagicMock:
        r = MagicMock()
        r.fetchall.return_value = []
        if idx == 0:
            r.fetchone.return_value = None
        elif idx == 1:
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


_PATCH_SCOPED_TIENE = patch(
    "app.services.permisos_service.PermisosService.tiene_permiso",
    return_value=False,
)
_PATCH_SCOPED_OBTENER = patch(
    "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
    return_value={"consultas.ver_mi_ranking"},
)
_PATCH_ALGUN_TRUE = patch(
    "app.services.permisos_service.PermisosService.tiene_algun_permiso",
    return_value=True,
)


@pytest.fixture()
def client_scoped_sub_pm(user_scoped_sub_pm):
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
        yield c, user_scoped_sub_pm, mock_db

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_async_db, None)


def _get_all_executed_sql(mock_db: MagicMock) -> list[str]:
    sqls = []
    for c in mock_db.execute.call_args_list:
        args = c.args
        if args:
            sqls.append(str(args[0]))
    return sqls


class TestConsultasMarcaSubPmScope:
    """Every scoped EXISTS branch + the PM-dropdown must reference marca_sub_pm."""

    def test_ranking_sql_includes_marca_sub_pm(self, client_scoped_sub_pm) -> None:
        client, user, mock_db = client_scoped_sub_pm
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking", headers=_auth(user))
        combined = " ".join(_get_all_executed_sql(mock_db))
        assert "marca_sub_pm" in combined

    def test_resumen_sql_includes_marca_sub_pm(self, client_scoped_sub_pm) -> None:
        client, user, mock_db = client_scoped_sub_pm
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/resumen", headers=_auth(user))
        combined = " ".join(_get_all_executed_sql(mock_db))
        assert "marca_sub_pm" in combined

    def test_kpis_sql_includes_marca_sub_pm(self, client_scoped_sub_pm) -> None:
        client, user, mock_db = client_scoped_sub_pm
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/kpis", headers=_auth(user))
        combined = " ".join(_get_all_executed_sql(mock_db))
        assert "marca_sub_pm" in combined

    def test_facets_sql_includes_marca_sub_pm(self, client_scoped_sub_pm) -> None:
        """facets endpoint's scoped EXISTS branches must reference marca_sub_pm."""
        client, user, mock_db = client_scoped_sub_pm
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/facets", headers=_auth(user))
        combined = " ".join(_get_all_executed_sql(mock_db))
        assert "marca_sub_pm" in combined

    def test_facets_pm_dropdown_stays_titular_only(self, client_scoped_sub_pm) -> None:
        """The pm-dropdown query (sourced from marcas_pm) must NOT UNION marca_sub_pm yet.

        PR1 keeps the dropdown listing only titulares because the pm-name FILTER
        joins (get_ranking/get_ranking_resumen/get_ranking_kpis/
        get_ranking_facets._pm_join_for_pe) still resolve via marcas_pm only.
        Unifying just the dropdown here would let a sub-PM be selected and then
        silently return zero rows. Dropdown + filter unify together in PR2 of
        sub-pm-scope-marcas (see the `ponytail:` marker in consultas.py).
        """
        client, user, mock_db = client_scoped_sub_pm
        with _PATCH_SCOPED_TIENE, _PATCH_SCOPED_OBTENER, _PATCH_ALGUN_TRUE:
            client.get("/api/consultas/ranking/facets", headers=_auth(user))
        sqls = _get_all_executed_sql(mock_db)
        pm_dropdown_calls = [sql for sql in sqls if "u.nombre" in sql and "marcas_pm" in sql]
        assert pm_dropdown_calls, "Expected a PM-dropdown query"
        for sql in pm_dropdown_calls:
            assert "marca_sub_pm" not in sql, f"PM dropdown query must stay titular-only in PR1, got: {sql[:400]}"
