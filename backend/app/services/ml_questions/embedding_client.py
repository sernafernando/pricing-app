"""
Embedding client for the dynamic similarity-selected few-shot flywheel
(sdd/ml-bot-dynamic-fewshot, design "Decision: `embed()` client seam").

Mirrors `llm_provider.OpenAICompatProvider`'s error-contract shape (retry on
5xx/timeout, no DB access, never raise into the caller) but with an
`Optional`-return contract instead of raise-on-failure: callers want a plain
`is None` check for cold-start/error fallback (ADR-1), not an exception on
the hot path.

The CLIENT owns both e5 prefixes (`"query: "` for buyer questions, `"passage:
"` for stored answers) so callers can never mismatch them, and owns
defensive truncation to the embedder's ~512-token input limit (a simple
char-budget heuristic — TEI's own tokenizer would still truncate, but we
never want to depend on that as the only safeguard).

ADR-5 / this module's contract: NEVER opens a DB session. `db` is accepted
only to thread through to `policy.get_config` for the `embedder_url` key —
callers (drafting_service, publisher_service) are responsible for calling
this OUTSIDE of any session they hold (mirrors `ml_client.get_item_description`).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional, Protocol

import httpx
from sqlalchemy.orm import Session

from app.services.ml_questions import policy

logger = logging.getLogger(__name__)

_EMBEDDING_DIM = 384
_MODEL = "intfloat/multilingual-e5-small"
_DEFAULT_BASE_URL = "http://192.168.1.231:8080"
_TIMEOUT_SECONDS = 5.0
_MAX_RETRIES = 2  # retry on transient 5xx/network errors only, mirrors llm_provider

# Defensive char-budget truncation heuristic: TEI's 512-token limit, at a very
# conservative ~4 chars/token for multilingual text, budgets comfortably under
# that ceiling so the embedder never rejects the request for exceeding its
# token limit. This is a heuristic cap, not an exact tokenizer count — the
# embedder's own tokenizer still truncates as a second line of defense.
_MAX_INPUT_CHARS = 2000

_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "


class EmbeddingProvider(Protocol):
    """Swap-safe provider interface (design ADR-1), mirrors `LlmProvider`."""

    async def embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Return one embedding per input text, in order. `None` on any
        failure (timeout, 5xx-after-retries, malformed body, dim mismatch,
        or a response with a different number of embeddings than inputs).
        Never raises."""
        ...


def _truncate(text: str) -> str:
    """Defensive char-budget cap, applied BEFORE the e5 prefix is added."""
    if len(text) > _MAX_INPUT_CHARS:
        return text[:_MAX_INPUT_CHARS]
    return text


def _resolve_base_url(db: Optional[Session]) -> str:
    """Read `embedder_url` from `ml_bot_config` (fail-safe: absent/malformed
    config, or no `db` provided, falls back to the default LAN URL)."""
    if db is None:
        return _DEFAULT_BASE_URL
    try:
        return policy.get_config(db, "embedder_url", cast=str, default=_DEFAULT_BASE_URL) or _DEFAULT_BASE_URL
    except Exception:  # noqa: BLE001 — config read must never break embedding
        logger.exception("embedding_client: failed to read embedder_url from ml_bot_config; using default")
        return _DEFAULT_BASE_URL


class TEIEmbeddingProvider:
    """`EmbeddingProvider` impl for a TEI (Text Embeddings Inference) or any
    OpenAI-compatible `/v1/embeddings` endpoint, via `httpx.AsyncClient`.
    Mirrors `OpenAICompatProvider`'s retry/error-contract shape (design
    "Alternatives: raise-on-failure (rejected)")."""

    def __init__(self, base_url: str, model: str = _MODEL, timeout_seconds: float = _TIMEOUT_SECONDS) -> None:
        self._base_url = base_url
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        payload = {"model": self._model, "input": texts}

        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(f"{self._base_url}/v1/embeddings", json=payload)

                if response.status_code >= 500:
                    logger.warning(
                        "embedding_client: transient server error (attempt %d/%d): %s",
                        attempt + 1,
                        _MAX_RETRIES + 1,
                        response.status_code,
                    )
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(min(2**attempt, 4))
                        continue
                    return None

                if response.status_code != 200:
                    logger.warning("embedding_client: non-200 response: %s", response.status_code)
                    return None

                return _parse_embeddings(response, expected_count=len(texts))

            except httpx.TimeoutException:
                logger.warning("embedding_client: timeout (attempt %d/%d)", attempt + 1, _MAX_RETRIES + 1)
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(min(2**attempt, 4))
                    continue
                return None
            except httpx.HTTPError as exc:
                logger.warning(
                    "embedding_client: network error (attempt %d/%d): %s", attempt + 1, _MAX_RETRIES + 1, exc
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(min(2**attempt, 4))
                    continue
                return None

        return None


def _parse_embeddings(response: httpx.Response, expected_count: int) -> Optional[List[List[float]]]:
    """Parse an OpenAI-compatible `/v1/embeddings` response body. Any parse
    failure, count mismatch, or dimension mismatch returns `None` — this
    module's error contract never raises to the caller."""
    try:
        data: Any = response.json()
        items = data["data"]
    except (ValueError, KeyError, TypeError):
        logger.warning("embedding_client: malformed response body (not valid JSON or missing 'data')")
        return None

    if not isinstance(items, list) or len(items) != expected_count:
        logger.warning(
            "embedding_client: response embedding count mismatch (expected %d, got %s)",
            expected_count,
            len(items) if isinstance(items, list) else type(items).__name__,
        )
        return None

    embeddings: List[List[float]] = []
    for item in items:
        try:
            embedding = item["embedding"]
        except (KeyError, TypeError):
            logger.warning("embedding_client: response item missing 'embedding' field")
            return None
        if not isinstance(embedding, list) or len(embedding) != _EMBEDDING_DIM:
            logger.warning(
                "embedding_client: embedding has wrong dimension (expected %d, got %s)",
                _EMBEDDING_DIM,
                len(embedding) if isinstance(embedding, list) else type(embedding).__name__,
            )
            return None
        embeddings.append(embedding)

    return embeddings


async def embed_query(text: str, db: Optional[Session] = None) -> Optional[List[float]]:
    """Embed a buyer question with the "query: " e5 prefix. Returns `None`
    on any failure (never raises) — caller falls back to the static
    few-shot path (design "Decision: Retrieval query + fallback")."""
    provider = TEIEmbeddingProvider(base_url=_resolve_base_url(db))
    result = await provider.embed([_QUERY_PREFIX + _truncate(text)])
    return result[0] if result else None


async def embed_passage(text: str, db: Optional[Session] = None) -> Optional[List[float]]:
    """Embed an answer/passage with the "passage: " e5 prefix. Returns
    `None` on any failure — caller skips capture entirely (design "Decision:
    Capture side-effect placement")."""
    provider = TEIEmbeddingProvider(base_url=_resolve_base_url(db))
    result = await provider.embed([_PASSAGE_PREFIX + _truncate(text)])
    return result[0] if result else None


async def embed_passages(texts: List[str], db: Optional[Session] = None) -> Optional[List[List[float]]]:
    """Batch variant of `embed_passage`, order-aligned with `texts`. Returns
    `None` (the whole batch) on any failure — an all-or-nothing contract,
    since a partially-embedded batch has no safe caller semantics yet."""
    provider = TEIEmbeddingProvider(base_url=_resolve_base_url(db))
    prefixed = [_PASSAGE_PREFIX + _truncate(text) for text in texts]
    return await provider.embed(prefixed)
