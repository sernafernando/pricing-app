"""
Tests de `POST /api/administracion/proveedores/sync-erp` — el sync híbrido.

El endpoint tiene dos caminos y este archivo fija el contrato de ambos:

  - `?supp_id=<int>`: una sola fila del ERP, sub-segundo. Sigue corriendo
    DENTRO del request y devuelve 200 con los contadores reales (502 si el ERP
    falla).
  - sin `supp_id`: el sync full recorre toda la tabla del ERP. NO puede
    ocupar el request, un worker del threadpool y la transacción durante todo
    el round-trip: se encola con `BackgroundTasks` y se responde 202. El job
    publica el resultado en el canal SSE `proveedores:sync`.

Notas de mocking:

  - El ERP (gbp-parser) SIEMPRE va mockeado: solo existe en producción.
  - `BackgroundTasks.add_task` se parchea para CAPTURAR sin ejecutar. El
    TestClient de Starlette corre las background tasks antes de devolver el
    control, así que sin este parche no se puede afirmar honestamente que la
    cadena no corrió dentro del request.
  - No hay pytest-asyncio en el proyecto (ver
    `tests/services/test_proveedores_sync_desde_erp.py`): las corrutinas se
    manejan con `asyncio.run(...)`.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks

from app.models.proveedor import Proveedor
from app.routers import administracion_proveedores as router_mod
from app.services.erp_worker_client import erp_worker_client

URL = "/api/administracion/proveedores/sync-erp"


@pytest.fixture
def con_permiso_gestionar():
    with patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True):
        yield


@pytest.fixture
def add_task_espia():
    """
    Reemplaza `BackgroundTasks.add_task` por un espía que registra y NO ejecuta.

    Devuelve la lista de `(func, args, kwargs)` encoladas.
    """
    encoladas: list[tuple] = []

    def espia(self, func, *args, **kwargs) -> None:
        encoladas.append((func, args, kwargs))

    with patch.object(BackgroundTasks, "add_task", espia):
        yield encoladas


def _fila(supp_id: int, nombre: str = "Proveedor ERP", **extra) -> dict:
    return {"comp_id": 1, "supp_id": supp_id, "supp_name": nombre, **extra}


def _erp(filas) -> AsyncMock:
    return AsyncMock(return_value=filas)


# =============================================================================
# Camino 1 — `?supp_id=` corre DENTRO del request y devuelve los contadores
# =============================================================================


class TestSuppIdSincronico:
    def test_supp_id_sincroniza_en_el_request_y_devuelve_contadores(
        self, client, auth_headers, db, con_permiso_gestionar, add_task_espia
    ) -> None:
        """Una sola fila del ERP: el operador la pide y la ve en la respuesta."""
        erp = _erp([_fila(11, "Proveedor Puntual", supp_taxNumber="30-11111111-1")])

        with patch.object(erp_worker_client, "get_suppliers", new=erp):
            r = client.post(f"{URL}?supp_id=11", headers=auth_headers)

        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["queued"] is False
        assert body["total_erp"] == 1
        assert body["insertados"] == 1

        # La cadena corrió DENTRO del request: el ERP fue consultado y el
        # proveedor ya está persistido cuando la respuesta vuelve.
        erp.assert_awaited_once_with(supp_id=11)
        assert add_task_espia == []
        assert db.query(Proveedor).filter(Proveedor.supp_id == 11).count() == 1

    def test_supp_id_con_erp_caido_responde_502(
        self, client, auth_headers, con_permiso_gestionar, add_task_espia
    ) -> None:
        """
        El contrato fail-loud del camino sincrónico no cambió.

        El `detail` string del HTTPException lo normaliza
        `app.core.exceptions.http_exception_handler` al envelope
        `{"error": {"code", "message"}}`.
        """
        with patch.object(erp_worker_client, "get_suppliers", new=_erp([])):
            r = client.post(f"{URL}?supp_id=11", headers=auth_headers)

        assert r.status_code == 502
        assert "no devolvió proveedores" in r.json()["error"]["message"]
        assert add_task_espia == []

    def test_sin_permiso_403(self, client, auth_headers, add_task_espia) -> None:
        """El permiso se chequea en el REQUEST, antes de cualquier trabajo."""
        with patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=False):
            r = client.post(URL, headers=auth_headers)

        assert r.status_code == 403
        assert add_task_espia == []


# =============================================================================
# Camino 2 — sync full: 202, no corre en el request, queda encolado
# =============================================================================


class TestFullEncolado:
    def test_sin_supp_id_responde_202_sin_ejecutar_la_cadena(
        self, client, auth_headers, db, con_permiso_gestionar, add_task_espia
    ) -> None:
        erp = _erp([_fila(11)])

        with patch.object(erp_worker_client, "get_suppliers", new=erp):
            r = client.post(URL, headers=auth_headers)

        assert r.status_code == 202
        body = r.json()
        assert body["queued"] is True
        assert body["channel"] == "proveedores:sync"
        # 202 no puede traer contadores: todavía no se hizo nada.
        assert "insertados" not in body

        # El trabajo NO ocurrió dentro del request.
        erp.assert_not_awaited()
        assert db.query(Proveedor).count() == 0

    def test_sin_supp_id_encola_el_job_de_background(
        self, client, auth_headers, con_permiso_gestionar, add_task_espia
    ) -> None:
        with patch.object(erp_worker_client, "get_suppliers", new=_erp([_fila(11)])):
            r = client.post(URL, headers=auth_headers)

        assert r.status_code == 202
        assert len(add_task_espia) == 1
        func, args, kwargs = add_task_espia[0]
        assert func is router_mod._sync_proveedores_erp_background
        assert args == ()
        assert kwargs == {}


# =============================================================================
# El job de background: publica por SSE, nunca levanta
# =============================================================================


def _correr_job(db, erp_mock, sse_mock):
    """
    Corre `_sync_proveedores_erp_background()` con la sesión de test, el ERP y
    el publisher SSE mockeados.

    `get_background_db` se reemplaza por un contextmanager que cede la sesión
    del fixture `db` sin commitear ni cerrarla: `_persistir_sync` ya commitea, y
    el fixture reinicia el SAVEPOINT después de cada commit.
    """

    @contextmanager
    def fake_background_db():
        yield db

    with (
        patch.object(router_mod, "get_background_db", fake_background_db),
        patch.object(router_mod, "sse_publish", sse_mock),
        patch.object(erp_worker_client, "get_suppliers", new=erp_mock),
    ):
        asyncio.run(router_mod._sync_proveedores_erp_background())


class TestJobDeBackground:
    def test_publica_los_contadores_por_sse_al_terminar_bien(self, db) -> None:
        sse = AsyncMock()

        _correr_job(db, _erp([_fila(11, "Uno"), _fila(12, "Dos")]), sse)

        sse.assert_awaited_once()
        canal, payload = sse.await_args.args
        assert canal == "proveedores:sync"
        assert payload["success"] is True
        assert payload["total_erp"] == 2
        assert payload["insertados"] == 2
        assert payload["actualizados"] == 0
        assert payload["rma_insertados"] == 2
        assert payload["vinculados_rma"] == 0
        assert db.query(Proveedor).count() == 2

    def test_abre_su_propia_sesion_y_no_la_del_request(self, db) -> None:
        """
        La sesión del endpoint ya está cerrada cuando el job corre (la 202 se
        envió antes), así que el job DEBE pedir la suya con `get_background_db`.
        """
        llamadas: list[int] = []

        @contextmanager
        def fake_background_db():
            llamadas.append(1)
            yield db

        with (
            patch.object(router_mod, "get_background_db", fake_background_db),
            patch.object(router_mod, "sse_publish", AsyncMock()),
            patch.object(erp_worker_client, "get_suppliers", new=_erp([_fila(11)])),
        ):
            asyncio.run(router_mod._sync_proveedores_erp_background())

        assert llamadas == [1]

    def test_erp_sync_error_se_publica_y_no_sale_del_job(self, db) -> None:
        """El ERP vacío levanta `ErpSyncError` dentro de la cadena canónica."""
        sse = AsyncMock()

        # `asyncio.run` re-lanzaría cualquier excepción que escape del job.
        _correr_job(db, _erp([]), sse)

        sse.assert_awaited_once()
        canal, payload = sse.await_args.args
        assert canal == "proveedores:sync"
        assert payload["success"] is False
        assert "no devolvió proveedores" in payload["error"]
        assert db.query(Proveedor).count() == 0

    def test_error_inesperado_se_publica_y_no_sale_del_job(self, db) -> None:
        """Cualquier otra excepción tampoco puede propagarse fuera de la task."""
        sse = AsyncMock()

        _correr_job(db, AsyncMock(side_effect=RuntimeError("boom")), sse)

        sse.assert_awaited_once()
        payload = sse.await_args.args[1]
        assert payload["success"] is False
        assert "boom" in payload["error"]

    def test_fallo_del_publish_sse_no_rompe_un_sync_ya_commiteado(self, db) -> None:
        """
        El sync ya commiteó cuando se publica. Si el publish revienta, el
        resultado NO se pierde ni la task explota: se loguea y se sigue.
        """
        sse = AsyncMock(side_effect=RuntimeError("redis caído"))

        _correr_job(db, _erp([_fila(11, "Persistido igual")]), sse)

        sse.assert_awaited_once()
        assert db.query(Proveedor).filter(Proveedor.supp_id == 11).count() == 1
