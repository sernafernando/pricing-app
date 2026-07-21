"""
Unit tests — services/ml_questions/embedding_client.py (ml-bot-dynamic-fewshot
PR1, task 3.1).

Covers (design "embed() client seam", spec Requirements 1 & 2):
- `embed_query` applies the "query: " e5 prefix; `embed_passage` applies
  "passage: ".
- Defensive char-budget truncation before the HTTP call.
- `embed_passages` batch shape, order-aligned.
- Base URL sourced from `ml_bot_config.embedder_url` via `policy.get_config`,
  default `http://192.168.1.231:8080`.
- Never raises: timeout, non-200, malformed JSON, wrong-dim embedding all
  return `None` (logged).
- No DB session import anywhere in the module (ADR-5: embedder called OUTSIDE
  any session).

No pytest-asyncio in this project — async code is driven with asyncio.run(),
mirroring test_ml_bot_llm_provider.py.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.services.ml_questions import embedding_client
from app.services.ml_questions.embedding_client import (
    embed_passage,
    embed_passages,
    embed_query,
)

_DIM = 384
_VALID_EMBEDDING = [0.01] * _DIM


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _patch_client(monkeypatch, transport):
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


class TestNoDbSessionImport:
    def test_module_never_opens_or_queries_a_db_session(self) -> None:
        """`Session` may appear only as a type hint (threaded through to
        `policy.get_config`); the module itself must never open a session
        (`get_db`/`sessionmaker`) or execute a query/commit."""
        import inspect

        source = inspect.getsource(embedding_client)
        assert "get_db" not in source
        assert "sessionmaker" not in source
        assert ".query(" not in source
        assert ".commit(" not in source


class TestPrefixApplication:
    def test_embed_query_applies_query_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            captured["input"] = body["input"]
            return httpx.Response(200, json={"data": [{"embedding": _VALID_EMBEDDING}]})

        _patch_client(monkeypatch, _mock_transport(handler))
        result = asyncio.run(embed_query("¿Tienen stock?"))
        assert result == _VALID_EMBEDDING
        assert captured["input"] == ["query: ¿Tienen stock?"]

    def test_embed_passage_applies_passage_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            captured["input"] = body["input"]
            return httpx.Response(200, json={"data": [{"embedding": _VALID_EMBEDDING}]})

        _patch_client(monkeypatch, _mock_transport(handler))
        result = asyncio.run(embed_passage("Sí, tenemos stock disponible."))
        assert result == _VALID_EMBEDDING
        assert captured["input"] == ["passage: Sí, tenemos stock disponible."]


class TestTruncation:
    def test_long_text_is_truncated_before_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            captured["input"] = body["input"]
            return httpx.Response(200, json={"data": [{"embedding": _VALID_EMBEDDING}]})

        _patch_client(monkeypatch, _mock_transport(handler))
        long_text = "a" * 5000
        asyncio.run(embed_passage(long_text))
        sent = captured["input"][0]
        # Prefix + truncated body must stay within the module's char budget.
        assert len(sent) <= embedding_client._MAX_INPUT_CHARS + len("passage: ")
        assert len(sent) < len("passage: ") + len(long_text)


class TestBatch:
    def test_embed_passages_returns_order_aligned_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        embeddings = [[0.01] * _DIM, [0.02] * _DIM]

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["input"] == ["passage: uno", "passage: dos"]
            return httpx.Response(
                200,
                json={"data": [{"embedding": e} for e in embeddings]},
            )

        _patch_client(monkeypatch, _mock_transport(handler))
        result = asyncio.run(embed_passages(["uno", "dos"]))
        assert result == embeddings


class TestBaseUrlFromConfig:
    def test_reads_embedder_url_from_ml_bot_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}

        def fake_get_config(db, clave, cast=str, default=None):
            assert clave == "embedder_url"
            return "http://custom-embedder:9090"

        monkeypatch.setattr(embedding_client.policy, "get_config", fake_get_config)

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"data": [{"embedding": _VALID_EMBEDDING}]})

        _patch_client(monkeypatch, _mock_transport(handler))
        asyncio.run(embed_query("hola", db=object()))
        assert captured["url"] == "http://custom-embedder:9090/v1/embeddings"

    def test_defaults_when_config_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"data": [{"embedding": _VALID_EMBEDDING}]})

        _patch_client(monkeypatch, _mock_transport(handler))
        asyncio.run(embed_query("hola"))
        assert captured["url"] == "http://192.168.1.231:8080/v1/embeddings"


class TestFailureModes:
    def test_timeout_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        _patch_client(monkeypatch, _mock_transport(handler))
        assert asyncio.run(embed_query("hola")) is None

    def test_non_200_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        _patch_client(monkeypatch, _mock_transport(handler))
        assert asyncio.run(embed_query("hola")) is None

    def test_malformed_json_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json")

        _patch_client(monkeypatch, _mock_transport(handler))
        assert asyncio.run(embed_query("hola")) is None

    def test_missing_embedding_field_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{}]})

        _patch_client(monkeypatch, _mock_transport(handler))
        assert asyncio.run(embed_query("hola")) is None

    def test_wrong_dimension_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

        _patch_client(monkeypatch, _mock_transport(handler))
        assert asyncio.run(embed_query("hola")) is None

    def test_empty_data_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": []})

        _patch_client(monkeypatch, _mock_transport(handler))
        assert asyncio.run(embed_query("hola")) is None

    def test_batch_partial_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A malformed batch response is an all-or-nothing failure: None."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"embedding": _VALID_EMBEDDING}]})

        _patch_client(monkeypatch, _mock_transport(handler))
        # Two inputs requested but only one embedding returned -> malformed.
        result = asyncio.run(embed_passages(["uno", "dos"]))
        assert result is None
