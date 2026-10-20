"""The ranking endpoints exclude combos through `combo_componentes`, not the
ERP mirror `tb_item_association` (combos-propios C2), and refuse to answer
while that table is still empty.

The ranking SQL is Postgres-only (LATERAL, ANY), so like the other consultas
tests this runs on a mock session: each endpoint gets the canned results its
own tests already use, so it completes with a 200, and the SQL it receives is
inspected. The predicate itself is proven against a real table in
`tests/services/combos/test_lectores_combo_componentes.py`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.combos.componentes import DETALLE_COMBOS_NO_SINCRONIZADOS, sql_no_es_combo
from tests.integration.combos_mock import con_chequeo_de_combos
from tests.integration.test_consultas_ranking import (  # noqa: F401  (fixtures)
    _PATCH_OBTENER_PERMISOS,
    _PATCH_TIENE_PERMISO_TRUE,
    _auth,
    _make_mock_db_session,
    _make_resumen_mock_db_session,
    rol_consultas,
    user_con_permiso,
)
from tests.integration.test_consultas_ranking_kpis import _make_kpis_mock_db_session

RANKING, RESUMEN, KPIS = "/api/consultas/ranking", "/api/consultas/ranking/resumen", "/api/consultas/ranking/kpis"
_CANNED = {RANKING: _make_mock_db_session, RESUMEN: _make_resumen_mock_db_session, KPIS: _make_kpis_mock_db_session}


def _assert_shape(path: str, body: dict) -> None:
    if path == RANKING:
        assert body["items"] == [] and body["total"] == 0
    elif path == RESUMEN:
        assert body["items"][0]["grupo"] == "TestBrand" and body["totales"]["num_productos"] == 3
    else:
        assert body["total_productos"] == 42


def _client(user, path: str, combos_sincronizados: bool):
    """Context manager: (client, executed SQL list) over the canned session."""
    from starlette.testclient import TestClient

    from app.core.database import get_async_db, get_db
    from app.main import app

    # The canned makers already answer the readiness check as synced; wrap
    # again so this test decides the answer (the outer wrapper sees it first).
    mock_db = con_chequeo_de_combos(_CANNED[path](), sincronizados=combos_sincronizados)
    executed: list[str] = []
    traced = mock_db.execute

    def _execute(stmt, *args, **kwargs):
        executed.append(str(stmt))
        return traced(stmt, *args, **kwargs)

    mock_db.execute = MagicMock(side_effect=_execute)

    def _override_get_db():
        yield mock_db

    async def _override_get_async_db():
        yield mock_db

    class _Ctx:
        def __enter__(self):
            app.dependency_overrides[get_db] = _override_get_db
            app.dependency_overrides[get_async_db] = _override_get_async_db
            self._tc = patch("app.routers.consultas._get_tc_venta", return_value=1000.0)
            self._tc.start()
            self._client = TestClient(app, raise_server_exceptions=False).__enter__()
            return self._client, executed

        def __exit__(self, *exc):
            self._client.__exit__(*exc)
            self._tc.stop()
            app.dependency_overrides.clear()

    return _Ctx()


def _get(client, user, path: str, incluir_combos: str):
    with _PATCH_TIENE_PERMISO_TRUE, _PATCH_OBTENER_PERMISOS:
        return client.get(path, params={"incluir_combos": incluir_combos}, headers=_auth(user))


@pytest.mark.parametrize("path", [RANKING, RESUMEN, KPIS])
def test_excluding_combos_reads_the_app_table(user_con_permiso, path: str) -> None:  # noqa: F811
    with _client(user_con_permiso, path, combos_sincronizados=True) as (client, executed):
        response = _get(client, user_con_permiso, path, "false")

    assert response.status_code == 200, response.text
    _assert_shape(path, response.json())
    filtered = [sql for sql in executed if "pe.item_id" in sql]
    assert filtered, f"{path} ran no product query"
    assert all(sql_no_es_combo("pe.item_id") in sql for sql in filtered)
    assert not any("tb_item_association" in sql for sql in executed)


@pytest.mark.parametrize("path", [RANKING, RESUMEN, KPIS])
def test_including_combos_does_not_filter_them(user_con_permiso, path: str) -> None:  # noqa: F811
    with _client(user_con_permiso, path, combos_sincronizados=False) as (client, executed):
        response = _get(client, user_con_permiso, path, "true")

    # Not filtering combos needs no bill of materials: an empty table is fine.
    assert response.status_code == 200, response.text
    _assert_shape(path, response.json())
    assert executed
    assert not any("combo_componentes" in sql or "tb_item_association" in sql for sql in executed)


@pytest.mark.parametrize("path", [RANKING, RESUMEN, KPIS])
def test_excluding_combos_with_an_empty_bom_is_503(user_con_permiso, path: str) -> None:  # noqa: F811
    with _client(user_con_permiso, path, combos_sincronizados=False) as (client, executed):
        response = _get(client, user_con_permiso, path, "false")

    assert response.status_code == 503
    assert response.json() == {"error": DETALLE_COMBOS_NO_SINCRONIZADOS}
    assert not any("pe.item_id" in sql for sql in executed)
