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


def _instant_sleep():
    """Replaces asyncio.sleep so tests do not pay the real backoff (0.4s
    doubling = ~6s per test). Does not change the attempt count."""

    async def _sleep(_seconds: float) -> None:
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
    """The retry code was correct but no test exercised it: the 500 test ran
    with `_max_attempts=1`, so it never actually retried. These tests count
    attempts, which is the only thing that proves the ladder exists and did
    not get broken by a refactor."""

    def test_transient_status_is_retried_the_full_ladder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Uses a READ: the ladder applies to reads. Writes deliberately get a
        single attempt -- see TestWritesAreNotBlindlyRetried."""
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(500, content=b"")

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep())
        client = _client()

        with pytest.raises(VikunjaTransientError):
            asyncio.run(client.list_tasks(project_id=7))

        assert attempts["n"] == 5, "the ladder must exhaust all 5 attempts before giving up"

    def test_permanent_status_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 4xx is the request's own fault: retrying only burns the 60
        requests-per-minute budget with no chance of succeeding."""
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(422, json={"message": "invalid"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = _client()

        with pytest.raises(VikunjaPermanentError):
            asyncio.run(client.create_task(project_id=7, title="hola"))

        assert attempts["n"] == 1, "a 4xx is never retried"


class TestTransientBoundaries:
    """429 and 408 are 4xx but are NOT the request's fault: one is rate
    limiting, the other a server-side request timeout. Classifying them as
    permanent would discard tickets that merely needed a retry."""

    @pytest.mark.parametrize("status", [429, 408])
    def test_rate_limit_and_request_timeout_are_transient(self, monkeypatch: pytest.MonkeyPatch, status: int) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, content=b"")

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = _client()

        with pytest.raises(VikunjaTransientError):
            asyncio.run(client.create_task(project_id=7, title="hola", _max_attempts=1))

    @pytest.mark.parametrize(
        "exception",
        [httpx.TimeoutException("timed out"), httpx.ConnectError("no connection")],
    )
    def test_network_failures_are_transient(self, monkeypatch: pytest.MonkeyPatch, exception: Exception) -> None:
        """A timeout or dropped connection on a WRITE is ambiguous, not
        failed: Vikunja may have created the task anyway. It must surface as
        transient so the ambiguity resolution downstream can pick it up."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise exception

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = _client()

        with pytest.raises(VikunjaTransientError):
            asyncio.run(client.create_task(project_id=7, title="hola", _max_attempts=1))


class TestWritesAreNotBlindlyRetried:
    """`create_task` is a PUT that CREATES a task: every call makes a new one.
    Retrying it after a lost acknowledgement is how the same ticket ends up in
    Vikunja five times -- and the ledger's UNIQUE(ticket_id) would not catch
    it, because that prevents a duplicate ROW, not a duplicate TASK. The
    ambiguity has to reach the caller so it can search-and-adopt instead."""

    def test_timeout_on_create_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            raise httpx.TimeoutException("timed out")

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep())
        client = _client()

        with pytest.raises(VikunjaTransientError):
            asyncio.run(client.create_task(project_id=7, title="hola"))

        assert attempts["n"] == 1, "a timed-out create must reach Vikunja exactly once"

    def test_server_error_on_create_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(500, content=b"")

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep())
        client = _client()

        with pytest.raises(VikunjaTransientError):
            asyncio.run(client.create_task(project_id=7, title="hola"))

        assert attempts["n"] == 1, "a 5xx on a write is ambiguous too: Vikunja may have committed it"

    def test_rate_limit_on_create_is_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """429 and 408 stay retryable even for writes: the server rejected the
        request without processing it, so no task can have been created."""
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] < 3:
                return httpx.Response(429, content=b"")
            return httpx.Response(200, json={"id": 7})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep())
        client = _client()

        result = asyncio.run(client.create_task(project_id=7, title="hola"))

        assert result["id"] == 7
        assert attempts["n"] == 3

    def test_reads_keep_the_full_ladder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The restriction is about writes only; listing is safe to retry."""
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] < 3:
                return httpx.Response(500, content=b"")
            return httpx.Response(200, json=[{"id": 1}], headers={"x-pagination-total-pages": "1"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep())
        client = _client()

        result = asyncio.run(client.list_tasks(project_id=7))

        assert [t["id"] for t in result] == [1]
        assert attempts["n"] == 3


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
