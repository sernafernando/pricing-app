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
    EMBED_MAX_CLIENT_BATCH_SIZE,
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


class TestClientBatchChunking:
    """TEI enforces `max_client_batch_size` (32 on our instance) and answers
    a bigger batch with **413**, which is not a 5xx and so was never even
    retried — `embed_passages` just returned `None`. Verified live against
    the embedder: n=32 -> 200, n=33 -> 413 "batch size 33 > maximum allowed
    batch size 32". The TN category sync hit this the moment the catalog
    grew past 32 paths.
    """

    def test_a_batch_over_the_limit_is_split_into_conforming_requests(self, monkeypatch: pytest.MonkeyPatch) -> None:
        batch_sizes = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            batch_sizes.append(len(payload["input"]))
            if len(payload["input"]) > EMBED_MAX_CLIENT_BATCH_SIZE:
                # Exactly what the real TEI does — the bug under test.
                return httpx.Response(413, json={"message": "batch size too large", "code": 413})
            return httpx.Response(
                200,
                json={"data": [{"object": "embedding", "embedding": _VALID_EMBEDDING} for _ in payload["input"]]},
            )

        _patch_client(monkeypatch, _mock_transport(handler))

        texts = [f"categoria {i}" for i in range(70)]
        result = asyncio.run(embed_passages(texts))

        assert result is not None, "a 70-text batch must succeed, not return None"
        assert len(result) == 70
        assert batch_sizes == [32, 32, 6]
        assert all(size <= EMBED_MAX_CLIENT_BATCH_SIZE for size in batch_sizes)

    def test_exactly_the_limit_stays_a_single_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            calls.append(len(payload["input"]))
            return httpx.Response(
                200,
                json={"data": [{"object": "embedding", "embedding": _VALID_EMBEDDING} for _ in payload["input"]]},
            )

        _patch_client(monkeypatch, _mock_transport(handler))

        result = asyncio.run(embed_passages([f"c {i}" for i in range(EMBED_MAX_CLIENT_BATCH_SIZE)]))

        assert result is not None
        assert calls == [EMBED_MAX_CLIENT_BATCH_SIZE]

    def test_order_is_preserved_across_chunks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Order alignment is the whole contract of `embed_passages` — a
        # chunked implementation that concatenates out of order would map
        # every category path to the wrong embedding, silently.
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "data": [
                        # Encode each text's index in the first component.
                        {"object": "embedding", "embedding": [float(int(text.split()[-1]))] + [0.0] * (_DIM - 1)}
                        for text in payload["input"]
                    ]
                },
            )

        _patch_client(monkeypatch, _mock_transport(handler))

        result = asyncio.run(embed_passages([f"categoria {i}" for i in range(70)]))

        assert result is not None
        assert [int(vec[0]) for vec in result] == list(range(70))

    def test_a_failing_chunk_fails_the_whole_batch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # All-or-nothing is the documented contract: a partially-embedded
        # batch would make the caller zip() mismatched pairs.
        state = {"calls": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            state["calls"] += 1
            if state["calls"] == 2:
                return httpx.Response(400, json={"message": "nope"})
            payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={"data": [{"object": "embedding", "embedding": _VALID_EMBEDDING} for _ in payload["input"]]},
            )

        _patch_client(monkeypatch, _mock_transport(handler))

        assert asyncio.run(embed_passages([f"c {i}" for i in range(70)])) is None

    def test_empty_input_makes_no_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("no request should be made for an empty batch")

        _patch_client(monkeypatch, _mock_transport(handler))

        assert asyncio.run(embed_passages([])) == []
