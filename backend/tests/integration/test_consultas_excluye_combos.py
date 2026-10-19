"""The ranking endpoints exclude combos through `combo_componentes`, not the
ERP mirror `tb_item_association` (combos-propios C2).

The ranking SQL is Postgres-only (LATERAL, ANY), so like the other consultas
tests this runs on a mock session and inspects the SQL it receives; the
predicate itself is proven against a real table in
`tests/services/combos/test_lectores_combo_componentes.py`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.combos.componentes import sql_no_es_combo
from tests.integration.test_consultas_ranking import (  # noqa: F401  (fixtures)
    _PATCH_OBTENER_PERMISOS,
    _PATCH_TIENE_PERMISO_TRUE,
    _auth,
    rol_consultas,
    user_con_permiso,
)

ENDPOINTS = ["/api/consultas/ranking", "/api/consultas/ranking/resumen", "/api/consultas/ranking/kpis"]


@pytest.fixture()
def client_capturing_sql(user_con_permiso):  # noqa: F811
    from starlette.testclient import TestClient

    from app.core.database import get_async_db, get_db
    from app.main import app

    executed: list[str] = []
    mock_db = MagicMock()

    def _execute(stmt, params=None):
        executed.append(str(stmt))
        return MagicMock()

    mock_db.execute.side_effect = _execute

    def _override_get_db():
        yield mock_db

    async def _override_get_async_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_async_db] = _override_get_async_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, user_con_permiso, executed
    app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ENDPOINTS)
def test_excluding_combos_reads_the_app_table(client_capturing_sql, path: str) -> None:
    client, user, executed = client_capturing_sql
    with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
        client.get(path, params={"incluir_combos": "false"}, headers=_auth(user))

    filtered = [sql for sql in executed if "pe.item_id" in sql]
    assert filtered, f"{path} ran no product query"
    assert all(sql_no_es_combo("pe.item_id") in sql for sql in filtered)
    assert not any("tb_item_association" in sql for sql in executed)


@pytest.mark.parametrize("path", ENDPOINTS)
def test_including_combos_does_not_filter_them(client_capturing_sql, path: str) -> None:
    client, user, executed = client_capturing_sql
    with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
        client.get(path, params={"incluir_combos": "true"}, headers=_auth(user))

    assert executed
    assert not any("combo_componentes" in sql or "tb_item_association" in sql for sql in executed)
