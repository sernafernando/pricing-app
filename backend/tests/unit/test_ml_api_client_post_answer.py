"""
Judgment Day slice E round 1: direct unit tests for
`MercadoLibreAPIClient.post_answer` — the only defense against
double-posting an answer when a retried publish crashes between the ML
POST succeeding and the terminal DB write (ADR-5).

Covers:
- Realistic ML "already answered" 400 body (structured message/error/cause
  fields) -> QuestionAlreadyAnsweredError.
- Unrelated 400 (validation error) -> AnswerPostPermanentError, NOT
  QuestionAlreadyAnsweredError.
- Non-JSON 400 body -> AnswerPostPermanentError + contract-drift WARNING
  logged.
- Other permanent 4xx (401/403/404/422) -> AnswerPostPermanentError.
- 2xx -> success, returns the parsed body.
- 5xx / network failure -> None (existing bounded-retry contract).

No pytest-asyncio in this project — async code is driven with asyncio.run().
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ml_api_client import (
    AnswerPostPermanentError,
    MercadoLibreAPIClient,
    QuestionAlreadyAnsweredError,
)


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def _client(monkeypatch: pytest.MonkeyPatch) -> MercadoLibreAPIClient:
    client = MercadoLibreAPIClient()
    monkeypatch.setattr(client, "get_access_token", lambda: _fake_token())
    return client


async def _fake_token() -> str:
    return "fake-token"


class TestPostAnswerAlreadyAnswered:
    def test_structured_already_answered_body_raises_already_answered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = {
            "message": "Question already has an answer",
            "error": "bad_request",
            "status": 400,
            "cause": [],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json=body)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        with pytest.raises(QuestionAlreadyAnsweredError):
            asyncio.run(client.post_answer(123, "respuesta"))

    def test_already_answered_signaled_via_cause_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = {
            "message": "invalid request",
            "error": "bad_request",
            "status": 400,
            "cause": [{"code": 123, "message": "the question is already answered"}],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json=body)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        with pytest.raises(QuestionAlreadyAnsweredError):
            asyncio.run(client.post_answer(123, "respuesta"))


class TestPostAnswerUnrelated400:
    def test_unrelated_validation_400_is_permanent_not_already_answered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = {
            "message": "text is required",
            "error": "bad_request",
            "status": 400,
            "cause": [],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json=body)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        with pytest.raises(AnswerPostPermanentError):
            asyncio.run(client.post_answer(123, "respuesta"))


class TestPostAnswerNonJsonBody:
    def test_non_json_400_body_is_permanent_and_logs_drift_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.services.ml_api_client as ml_api_client_module

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, content=b"<html>not json</html>")

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        warnings: list[str] = []
        monkeypatch.setattr(
            ml_api_client_module.logger,
            "warning",
            lambda msg, *args, **kwargs: warnings.append(msg % args if args else msg),
        )

        with pytest.raises(AnswerPostPermanentError):
            asyncio.run(client.post_answer(123, "respuesta"))

        assert any("contract" in w.lower() or "drift" in w.lower() for w in warnings)


class TestPostAnswerOtherPermanent4xx:
    @pytest.mark.parametrize("status_code", [401, 403, 404, 422])
    def test_other_4xx_are_permanent(self, monkeypatch: pytest.MonkeyPatch, status_code: int) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json={"message": "denied", "error": "forbidden"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        with pytest.raises(AnswerPostPermanentError) as exc_info:
            asyncio.run(client.post_answer(123, "respuesta"))
        assert exc_info.value.status_code == status_code


class TestPostAnswerSuccess:
    def test_2xx_returns_parsed_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": 999, "text": "respuesta"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        result = asyncio.run(client.post_answer(123, "respuesta"))
        assert result == {"id": 999, "text": "respuesta"}


class TestPostAnswerTransient:
    def test_5xx_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"message": "unavailable"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        result = asyncio.run(client.post_answer(123, "respuesta"))
        assert result is None

    def test_network_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        result = asyncio.run(client.post_answer(123, "respuesta"))
        assert result is None
