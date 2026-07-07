"""
LLM provider layer for the ML questions bot (Slice D1).

Implements design §6 stage 4 (provider call) + ADR-6 (swappable `LlmProvider`
Protocol, `GroqProvider` as the only MVP impl, no cost-cap logic).

The provider NEVER touches the DB and NEVER sees anything beyond the two
strings it is handed (system prompt + user payload) — ADR-2. Callers
(drafting_service, Slice D2) are responsible for building those strings from
a pre-scoped `ScopedContext` (see `context_builder.py`).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Closed output schema (R-302, design §6 stage 5): exactly these fields, no
# more, no less. Extra/missing fields -> reject -> caller routes to fallback.
_REQUIRED_FIELDS = frozenset({"answer", "confidence", "category", "can_answer"})

_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_DEFAULT_TIMEOUT_SECONDS = 15.0
_MAX_RETRIES = 2  # retries on transient 5xx/network errors only
_MAX_RESPONSE_BYTES = 256 * 1024  # 256 KB cap on the raw response body


class LlmProviderError(Exception):
    """Raised when the provider call fails (transient or permanent). Callers
    treat any raised error the same way: route to fallback (R-601)."""


@dataclass(frozen=True)
class LlmAnswer:
    """Parsed, schema-validated LLM output (R-302)."""

    answer: str
    confidence: float
    category: str
    can_answer: bool


class LlmProvider(Protocol):
    """Swap-safe provider interface (ADR-6). A provider only ever receives a
    system prompt and a user payload string — never a DB session, never a
    tool/function-calling surface (ADR-2 rejects that shape explicitly)."""

    async def complete(self, system_prompt: str, user_payload: str) -> str:
        """Return the raw text response from the LLM (expected to be a JSON
        string matching the closed schema). Raises `LlmProviderError` on
        failure; never returns a partial/garbage value silently."""
        ...

    def is_configured(self) -> bool:
        """Whether this provider has everything it needs to run (e.g. an API
        key). When False, callers must skip drafting and go straight to
        fallback — never crash."""
        ...


class GroqProvider:
    """`LlmProvider` implementation backed by the Groq chat-completions API
    (OpenAI-compatible surface), via `httpx`. Design §6 stage 4 / §11."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = _DEFAULT_MODEL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.GROQ_API_KEY
        self._base_url = base_url or settings.GROQ_BASE_URL
        self._model = model
        self._timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        """GROQ_API_KEY absent/empty -> provider unavailable. Drafting must
        report failure (route to fallback) instead of crashing (constraint)."""
        return bool(self._api_key and self._api_key.strip())

    async def complete(self, system_prompt: str, user_payload: str) -> str:
        if not self.is_configured():
            raise LlmProviderError("GroqProvider is not configured (missing GROQ_API_KEY)")

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        last_error: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                if response.status_code >= 500:
                    last_error = LlmProviderError(f"Groq server error: {response.status_code}")
                    logger.warning(
                        "GroqProvider transient error (attempt %d/%d): %s",
                        attempt + 1,
                        _MAX_RETRIES + 1,
                        response.status_code,
                    )
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(min(2**attempt, 4))
                    continue

                if response.status_code >= 400:
                    raise LlmProviderError(f"Groq client error: {response.status_code}")

                if len(response.content) > _MAX_RESPONSE_BYTES:
                    raise LlmProviderError(f"Groq response body exceeds max size of {_MAX_RESPONSE_BYTES} bytes")

                return _extract_content(response)

            except httpx.TimeoutException as exc:
                last_error = LlmProviderError(f"Groq request timed out: {exc}")
                logger.warning("GroqProvider timeout (attempt %d/%d)", attempt + 1, _MAX_RETRIES + 1)
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(min(2**attempt, 4))
                continue
            except httpx.HTTPError as exc:
                # Network-level failure (connection refused, DNS, etc.) — transient.
                last_error = LlmProviderError(f"Groq network error: {exc}")
                logger.warning(
                    "GroqProvider network error (attempt %d/%d): %s",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    exc,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(min(2**attempt, 4))
                continue

        assert last_error is not None
        raise last_error


def _extract_content(response: httpx.Response) -> str:
    """Parse a 200 response body and extract `choices[0].message.content`.

    A 200 status does NOT guarantee a well-formed body (moderation shape,
    HTML error page, empty `choices`, etc.) — any parse/extraction failure
    is normalized to `LlmProviderError` so callers only ever need to catch
    that single exception type (per this module's docstring contract).
    """
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise LlmProviderError(f"Groq response body is malformed: {type(exc).__name__}") from exc

    if not isinstance(content, str) or not content.strip():
        raise LlmProviderError("Groq response 'content' must be a non-empty string")

    return content


def parse_llm_output(raw: str) -> LlmAnswer:
    """Strict closed-schema parser (R-302, design §6 stage 5).

    Accepts ONLY a JSON object with exactly the fields `answer` (str),
    `confidence` (number), `category` (str), `can_answer` (bool) — no more,
    no less. Malformed JSON, missing fields, extra fields, or wrong types
    all raise `LlmProviderError` so the caller routes to fallback; this
    function never returns free-text or a partially-filled object.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise LlmProviderError(f"LLM output is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise LlmProviderError("LLM output is not a JSON object")

    fields = set(data.keys())
    if fields != _REQUIRED_FIELDS:
        raise LlmProviderError(f"LLM output schema mismatch: expected {sorted(_REQUIRED_FIELDS)}, got {sorted(fields)}")

    answer = data["answer"]
    confidence = data["confidence"]
    category = data["category"]
    can_answer = data["can_answer"]

    if not isinstance(answer, str) or not answer.strip():
        raise LlmProviderError("LLM output 'answer' must be a non-empty string")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise LlmProviderError("LLM output 'confidence' must be a number")
    if not (0.0 <= float(confidence) <= 1.0):
        raise LlmProviderError("LLM output 'confidence' must be between 0 and 1")
    if not isinstance(category, str) or not category.strip():
        raise LlmProviderError("LLM output 'category' must be a non-empty string")
    if not isinstance(can_answer, bool):
        raise LlmProviderError("LLM output 'can_answer' must be a boolean")

    return LlmAnswer(
        answer=answer,
        confidence=float(confidence),
        category=category,
        can_answer=can_answer,
    )
