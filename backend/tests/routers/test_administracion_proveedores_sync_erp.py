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
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks

from app.models.proveedor import Proveedor
from app.routers import administracion_proveedores as router_mod
from app.services.erp_worker_client import erp_worker_client
from app.services.proveedores_service import ProveedoresService

URL = "/api/administracion/proveedores/sync-erp"

RUN_ID = "0123456789abcdef0123456789abcdef"


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

    def test_sync_en_curso_responde_409(self, client, auth_headers, con_permiso_gestionar, add_task_espia) -> None:
        """
        409 Conflict y no 503/429: el servicio está sano (el resto de la API
        responde) y no es una cuota por cliente — el request choca con el estado
        actual del recurso, que es exactamente lo que 409 significa.
        """
        with (
            patch.object(erp_worker_client, "get_suppliers", new=_erp([_fila(11)])),
            patch.object(ProveedoresService, "_intentar_lock_sync", autospec=True, return_value=False),
        ):
            r = client.post(f"{URL}?supp_id=11", headers=auth_headers)

        assert r.status_code == 409
        assert "en curso" in r.json()["error"]["message"]


# =============================================================================
# DEFECTO 1 — `?supp_id=0` NO puede disparar el sync FULL dentro del request
# =============================================================================


class TestSuppIdInvalido:
    """
    La rama se elige por `supp_id is None`, así que `?supp_id=0` tomaba el
    camino SINCRÓNICO; y el cliente del ERP filtraba por truthiness, así que
    omitía `suppID` y traía la tabla ENTERA, persistiéndola dentro del request.
    Un sync full completo alcanzable con un query param por cualquiera que
    tenga `administracion.gestionar_proveedores`.
    """

    @pytest.mark.parametrize("valor", [0, -1], ids=["cero", "negativo"])
    def test_supp_id_fuera_de_rango_se_rechaza_con_422_sin_tocar_el_erp(
        self, client, auth_headers, db, con_permiso_gestionar, add_task_espia, valor
    ) -> None:
        erp = _erp([_fila(11)])

        with patch.object(erp_worker_client, "get_suppliers", new=erp):
            r = client.post(f"{URL}?supp_id={valor}", headers=auth_headers)

        assert r.status_code == 422
        # Lo importante: el ERP nunca se consultó y nada se persistió.
        erp.assert_not_awaited()
        assert add_task_espia == []
        assert db.query(Proveedor).count() == 0


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
        # El job recibe el MISMO `run_id` que se devolvió en la 202: es lo único
        # que permite al cliente correlacionar el evento SSE con su corrida.
        assert args == (r.json()["run_id"],)
        assert kwargs == {}

    def test_la_202_devuelve_un_run_id_distinto_por_corrida(
        self, client, auth_headers, con_permiso_gestionar, add_task_espia
    ) -> None:
        """
        `proveedores:sync` es un canal de broadcast global. Si dos corridas
        compartieran identificador, el resultado de una resolvería la otra y el
        defecto seguiría abierto.
        """
        with patch.object(erp_worker_client, "get_suppliers", new=_erp([_fila(11)])):
            primera = client.post(URL, headers=auth_headers).json()["run_id"]
            segunda = client.post(URL, headers=auth_headers).json()["run_id"]

        assert primera and segunda
        assert primera != segunda


# =============================================================================
# El job de background: publica por SSE, nunca levanta
# =============================================================================


def _correr_job(db, erp_mock, sse_mock, run_id: str = RUN_ID, extra_patches=()):
    """
    Corre `_sync_proveedores_erp_background(run_id)` con la sesión de test, el
    ERP y el publisher SSE mockeados.

    `get_background_db` se reemplaza por un contextmanager que cede la sesión
    del fixture `db` sin commitear ni cerrarla: `_persistir_sync` ya commitea, y
    el fixture reinicia el SAVEPOINT después de cada commit.
    """

    @contextmanager
    def fake_background_db():
        yield db

    with ExitStack() as stack:
        stack.enter_context(patch.object(router_mod, "get_background_db", fake_background_db))
        stack.enter_context(patch.object(router_mod, "sse_publish", sse_mock))
        stack.enter_context(patch.object(erp_worker_client, "get_suppliers", new=erp_mock))
        for p in extra_patches:
            stack.enter_context(p)
        asyncio.run(router_mod._sync_proveedores_erp_background(run_id))


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
            asyncio.run(router_mod._sync_proveedores_erp_background(RUN_ID))

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

    # DEFECTO 2 — sync ya en curso
    def test_sync_en_curso_publica_su_propio_payload_y_no_levanta(self, db) -> None:
        """
        Con el lock tomado por otro sync el job NO puede propagar (quedaría una
        excepción huérfana en la task de Starlette) ni inventar un fallo del
        ERP: publica un payload explícito de "ya hay un sync en curso" y no
        toca los contadores.
        """
        sse = AsyncMock()

        # `asyncio.run` re-lanzaría cualquier excepción que escape del job.
        _correr_job(
            db,
            _erp([_fila(11)]),
            sse,
            extra_patches=[patch.object(ProveedoresService, "_intentar_lock_sync", autospec=True, return_value=False)],
        )

        sse.assert_awaited_once()
        canal, payload = sse.await_args.args
        assert canal == "proveedores:sync"
        assert payload["success"] is False
        assert payload["en_curso"] is True
        assert "en curso" in payload["error"]
        # No se persistió nada y no se reportaron contadores falsos.
        assert "insertados" not in payload
        assert db.query(Proveedor).count() == 0


# =============================================================================
# DEFECTO 3 — todo payload SSE viaja correlacionado con su corrida
# =============================================================================


class TestCorrelacionRunId:
    """
    El canal es un broadcast global: sin `run_id` el resultado del sync de un
    usuario limpiaba el banner de otro, cancelaba su timeout y le mostraba
    contadores ajenos como propios. La correlación solo sirve si viaja en
    TODOS los caminos, incluidos los de error.
    """

    @pytest.mark.parametrize(
        "erp_mock, extra_patches, id_caso",
        [
            pytest.param(_erp([_fila(11)]), (), "exito", id="exito"),
            pytest.param(_erp([]), (), "erp-vacio", id="erp-sync-error"),
            pytest.param(AsyncMock(side_effect=RuntimeError("boom")), (), "inesperado", id="error-inesperado"),
        ],
    )
    def test_todos_los_payloads_llevan_el_run_id(self, db, erp_mock, extra_patches, id_caso) -> None:
        sse = AsyncMock()

        _correr_job(db, erp_mock, sse, run_id=RUN_ID, extra_patches=extra_patches)

        payload = sse.await_args.args[1]
        assert payload["run_id"] == RUN_ID

    def test_el_payload_de_sync_en_curso_tambien_lleva_el_run_id(self, db) -> None:
        sse = AsyncMock()

        _correr_job(
            db,
            _erp([_fila(11)]),
            sse,
            run_id=RUN_ID,
            extra_patches=[patch.object(ProveedoresService, "_intentar_lock_sync", autospec=True, return_value=False)],
        )

        assert sse.await_args.args[1]["run_id"] == RUN_ID

    def test_el_run_id_de_la_202_es_el_que_viaja_por_sse(
        self, client, auth_headers, db, con_permiso_gestionar, add_task_espia
    ) -> None:
        """
        Cierra el circuito completo: el identificador que el cliente guarda del
        202 es EXACTAMENTE el que después tiene que matchear contra el evento.
        """
        with patch.object(erp_worker_client, "get_suppliers", new=_erp([_fila(11)])):
            r = client.post(URL, headers=auth_headers)

        run_id_202 = r.json()["run_id"]
        func, args, _ = add_task_espia[0]

        sse = AsyncMock()
        _correr_job(db, _erp([_fila(11)]), sse, run_id=args[0])

        assert sse.await_args.args[1]["run_id"] == run_id_202
