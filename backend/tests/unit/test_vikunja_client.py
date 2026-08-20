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
