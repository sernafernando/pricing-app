"""RED/GREEN for the async Vikunja client (sdd/tickets-sync-vikunja PR 1,
tasks 1.4-1.7).

No pytest-asyncio in this project — async code is driven with
asyncio.run() (canon: test_ml_api_client_post_answer.py). Uses
httpx.MockTransport monkeypatched into httpx.AsyncClient.__init__, exactly
like the ML client tests, since the Vikunja client opens a fresh
AsyncClient per call (timeout=15.0, per the design's event-loop-safety
requirement).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.vikunja_client import (
    VikunjaClient,
    VikunjaPermanentError,
    VikunjaTransientError,
)


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def _client() -> VikunjaClient:
    return VikunjaClient(base_url="http://vikunja.local", token="secret-token")


def _sleep_instantaneo():
    """Reemplaza asyncio.sleep para no pagar los backoffs reales (0.4s
    duplicando = 6s por test). No altera el conteo de intentos."""

    async def _sleep(_segundos: float) -> None:
        return None

    return _sleep


class TestCreateTask:
    def test_create_task_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PUT"
            assert request.url.path == "/api/v1/projects/7/tasks"
            assert request.headers["Authorization"] == "Bearer secret-token"
            return httpx.Response(200, json={"id": 42, "title": "hola"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = _client()

        result = asyncio.run(client.create_task(project_id=7, title="hola", description="<p>hola</p>"))
        assert result["id"] == 42
        assert result["title"] == "hola"

    def test_create_task_permanent_error_on_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"message": "invalid"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = _client()

        with pytest.raises(VikunjaPermanentError):
            asyncio.run(client.create_task(project_id=7, title="hola"))

    def test_create_task_transient_error_on_bare_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Vikunja's SQLite 'database is locked' arrives as a bare 500 with
        nothing informative in the body — must classify by status code only,
        never by parsing the body."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, content=b"")

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = _client()

        with pytest.raises(VikunjaTransientError):
            asyncio.run(client.create_task(project_id=7, title="hola", _max_attempts=1))


class TestRetryLadder:
    """El código de reintento estaba bien, pero ningún test lo ejercitaba: el
    test del 500 corría con `_max_attempts=1`, así que nunca reintentaba.
    Estos tests cuentan intentos, que es lo único que prueba que la escalera
    existe y no se rompió en un refactor."""

    def test_transient_status_is_retried_the_full_ladder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        intentos = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            intentos["n"] += 1
            return httpx.Response(500, content=b"")

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        monkeypatch.setattr(asyncio, "sleep", _sleep_instantaneo())
        client = _client()

        with pytest.raises(VikunjaTransientError):
            asyncio.run(client.create_task(project_id=7, title="hola"))

        assert intentos["n"] == 5, "la escalera tiene que agotar los 5 intentos antes de rendirse"

    def test_permanent_status_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Un 4xx es culpa del pedido: reintentarlo solo quema el presupuesto
        de 60 pedidos por minuto sin ninguna chance de mejorar."""
        intentos = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            intentos["n"] += 1
            return httpx.Response(422, json={"message": "invalid"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = _client()

        with pytest.raises(VikunjaPermanentError):
            asyncio.run(client.create_task(project_id=7, title="hola"))

        assert intentos["n"] == 1, "un 4xx no se reintenta"

    def test_recovers_when_a_later_attempt_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Lo que realmente pasa con SQLite bajo carga: falla un par de veces
        y después entra. La escalera tiene que devolver el resultado, no la
        excepción del primer intento."""
        intentos = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            intentos["n"] += 1
            if intentos["n"] < 3:
                return httpx.Response(500, content=b"")
            return httpx.Response(200, json={"id": 99})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        monkeypatch.setattr(asyncio, "sleep", _sleep_instantaneo())
        client = _client()

        result = asyncio.run(client.create_task(project_id=7, title="hola"))

        assert result["id"] == 99
        assert intentos["n"] == 3


class TestTransientBoundaries:
    """429 y 408 son 4xx pero NO son culpa del pedido: uno es límite de tasa y
    el otro un timeout del servidor. Clasificarlos como permanentes descartaría
    tickets que solo había que reintentar."""

    @pytest.mark.parametrize("status", [429, 408])
    def test_rate_limit_and_request_timeout_are_transient(self, monkeypatch: pytest.MonkeyPatch, status: int) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, content=b"")

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = _client()

        with pytest.raises(VikunjaTransientError):
            asyncio.run(client.create_task(project_id=7, title="hola", _max_attempts=1))

    @pytest.mark.parametrize(
        "excepcion",
        [httpx.TimeoutException("se acabó el tiempo"), httpx.ConnectError("sin conexión")],
    )
    def test_network_failures_are_transient(self, monkeypatch: pytest.MonkeyPatch, excepcion: Exception) -> None:
        """Un timeout o una conexión caída en una ESCRITURA es ambiguo, no
        fallido: puede que Vikunja haya creado la tarea igual. Tiene que salir
        como transitorio para que la resolución de ambigüedad lo agarre."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise excepcion

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = _client()

        with pytest.raises(VikunjaTransientError):
            asyncio.run(client.create_task(project_id=7, title="hola", _max_attempts=1))


class TestListTasksPagination:
    def test_list_tasks_follows_pagination_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pages = {
            "1": [{"id": 1}, {"id": 2}],
            "2": [{"id": 3}],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            page = request.url.params.get("page", "1")
            return httpx.Response(
                200,
                json=pages[page],
                headers={"x-pagination-total-pages": "2"},
            )

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = _client()

        result = asyncio.run(client.list_tasks(project_id=7))
        assert [t["id"] for t in result] == [1, 2, 3]

    def test_list_tasks_single_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[{"id": 1}],
                headers={"x-pagination-total-pages": "1"},
            )

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = _client()

        result = asyncio.run(client.list_tasks(project_id=7))
        assert [t["id"] for t in result] == [1]
