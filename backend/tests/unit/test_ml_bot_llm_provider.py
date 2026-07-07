"""
T-D1a: Unit tests — services/ml_questions/llm_provider.py (Slice D1)

Covers (spec R-301/R-302, design §6 stage 4-5, ADR-2, ADR-6):
- GroqProvider.is_configured(): true/false based on GROQ_API_KEY presence.
- GroqProvider.complete(): happy path (mocked httpx transport), retry on
  transient 5xx, no-retry fail-fast on 4xx, timeout treated as transient.
- parse_llm_output(): strict closed-schema parser — accepts exactly
  {answer, confidence, category, can_answer}; rejects malformed JSON, missing
  fields, extra fields, wrong types, out-of-range confidence.
- Provider never crashes the caller — always raises LlmProviderError, never
  an unhandled exception type, and never returns free text.

No pytest-asyncio in this project — async code is driven with asyncio.run().
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.services.ml_questions.llm_provider import (
    GroqProvider,
    LlmProviderError,
    parse_llm_output,
)


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _patch_client(monkeypatch, transport):
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


class TestIsConfigured:
    def test_configured_when_api_key_present(self) -> None:
        provider = GroqProvider(api_key="sk-test-123")
        assert provider.is_configured() is True

    def test_not_configured_when_api_key_missing(self) -> None:
        provider = GroqProvider(api_key=None)
        assert provider.is_configured() is False

    def test_not_configured_when_api_key_blank(self) -> None:
        provider = GroqProvider(api_key="   ")
        assert provider.is_configured() is False


class TestComplete:
    def test_raises_when_not_configured(self) -> None:
        provider = GroqProvider(api_key=None)
        with pytest.raises(LlmProviderError):
            asyncio.run(provider.complete("system", "user"))

    def test_happy_path_returns_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = json.dumps({"answer": "hola", "confidence": 0.9, "category": "stock", "can_answer": True})

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer sk-test-123"
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": body}}]},
            )

        _patch_client(monkeypatch, _mock_transport(handler))
        provider = GroqProvider(api_key="sk-test-123")
        result = asyncio.run(provider.complete("system prompt", "user payload"))
        assert result == body

    def test_retries_on_5xx_then_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        attempts = {"count": 0}
        body = json.dumps({"answer": "hola", "confidence": 0.9, "category": "stock", "can_answer": True})

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] < 2:
                return httpx.Response(503, json={"error": "unavailable"})
            return httpx.Response(200, json={"choices": [{"message": {"content": body}}]})

        _patch_client(monkeypatch, _mock_transport(handler))
        provider = GroqProvider(api_key="sk-test-123")
        result = asyncio.run(provider.complete("system", "user"))
        assert result == body
        assert attempts["count"] == 2

    def test_exhausts_retries_on_persistent_5xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "unavailable"})

        _patch_client(monkeypatch, _mock_transport(handler))
        provider = GroqProvider(api_key="sk-test-123")
        with pytest.raises(LlmProviderError):
            asyncio.run(provider.complete("system", "user"))

    def test_fails_fast_on_4xx_no_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            return httpx.Response(401, json={"error": "unauthorized"})

        _patch_client(monkeypatch, _mock_transport(handler))
        provider = GroqProvider(api_key="sk-bad")
        with pytest.raises(LlmProviderError):
            asyncio.run(provider.complete("system", "user"))
        assert attempts["count"] == 1

    def test_timeout_treated_as_transient_and_exhausts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        provider = GroqProvider(api_key="sk-test-123")
        with pytest.raises(LlmProviderError):
            asyncio.run(provider.complete("system", "user"))


class TestParseLlmOutput:
    def test_valid_output_parses(self) -> None:
        raw = json.dumps(
            {"answer": "Hola, sí tenemos stock.", "confidence": 0.85, "category": "stock", "can_answer": True}
        )
        result = parse_llm_output(raw)
        assert result.answer == "Hola, sí tenemos stock."
        assert result.confidence == 0.85
        assert result.category == "stock"
        assert result.can_answer is True

    def test_malformed_json_rejected(self) -> None:
        with pytest.raises(LlmProviderError):
            parse_llm_output("not json at all {")

    def test_non_object_json_rejected(self) -> None:
        with pytest.raises(LlmProviderError):
            parse_llm_output(json.dumps(["a", "b"]))

    def test_missing_field_rejected(self) -> None:
        raw = json.dumps({"answer": "hola", "confidence": 0.9, "category": "stock"})
        with pytest.raises(LlmProviderError):
            parse_llm_output(raw)

    def test_extra_field_rejected(self) -> None:
        raw = json.dumps(
            {
                "answer": "hola",
                "confidence": 0.9,
                "category": "stock",
                "can_answer": True,
                "price": 1000,
            }
        )
        with pytest.raises(LlmProviderError):
            parse_llm_output(raw)

    def test_empty_answer_rejected(self) -> None:
        raw = json.dumps({"answer": "  ", "confidence": 0.9, "category": "stock", "can_answer": True})
        with pytest.raises(LlmProviderError):
            parse_llm_output(raw)

    def test_confidence_out_of_range_rejected(self) -> None:
        raw = json.dumps({"answer": "hola", "confidence": 1.5, "category": "stock", "can_answer": True})
        with pytest.raises(LlmProviderError):
            parse_llm_output(raw)

    def test_confidence_wrong_type_rejected(self) -> None:
        raw = json.dumps({"answer": "hola", "confidence": "high", "category": "stock", "can_answer": True})
        with pytest.raises(LlmProviderError):
            parse_llm_output(raw)

    def test_can_answer_wrong_type_rejected(self) -> None:
        raw = json.dumps({"answer": "hola", "confidence": 0.9, "category": "stock", "can_answer": "yes"})
        with pytest.raises(LlmProviderError):
            parse_llm_output(raw)

    def test_bool_confidence_rejected(self) -> None:
        # bool is a subclass of int in Python — must be explicitly rejected.
        raw = json.dumps({"answer": "hola", "confidence": True, "category": "stock", "can_answer": True})
        with pytest.raises(LlmProviderError):
            parse_llm_output(raw)
