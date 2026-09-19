"""Three-key Gemini pool. Rotates on 429/503. Never logs API keys."""

from __future__ import annotations

import json
import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("services.oc_match.gemini_pool")

JSON_CONFIG = types.GenerateContentConfig(
    response_mime_type="application/json",
    temperature=0.1,
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)


class MissingGeminiKeysError(RuntimeError):
    """No GEMINI_API_KEY / _2 / _3 configured."""


def _code(exc: BaseException) -> int | None:
    return getattr(exc, "code", None) or getattr(exc, "status_code", None)


def es_cuota(exc: BaseException) -> bool:
    code = _code(exc)
    return code == 429 or "RESOURCE_EXHAUSTED" in str(exc)


def es_demanda(exc: BaseException) -> bool:
    code = _code(exc)
    return code == 503 or "UNAVAILABLE" in str(exc)


def load_keys() -> tuple[list[str], str]:
    """Read keys from Settings. Raises MissingGeminiKeysError if none."""
    model = (settings.GEMINI_MODEL or "gemini-3.6-flash").strip()
    keys: list[str] = []
    seen: set[str] = set()
    for raw in (settings.GEMINI_API_KEY, settings.GEMINI_API_KEY_2, settings.GEMINI_API_KEY_3):
        value = (raw or "").strip()
        if value.startswith("#") or not value or value in seen:
            continue
        keys.append(value)
        seen.add(value)
    if not keys:
        raise MissingGeminiKeysError("Falta GEMINI_API_KEY (o GEMINI_API_KEY_2 / _3)")
    return keys, model


class GeminiPool:
    def __init__(self, keys: list[str], model: str) -> None:
        if not keys:
            raise MissingGeminiKeysError("Falta GEMINI_API_KEY (o GEMINI_API_KEY_2 / _3)")
        self.keys = keys
        self.model = model
        self.i = 0
        self.client = genai.Client(api_key=keys[0])

    @property
    def label(self) -> str:
        return f"key {self.i + 1}/{len(self.keys)}"

    def _rotar(self) -> None:
        self.i = (self.i + 1) % len(self.keys)
        self.client = genai.Client(api_key=self.keys[self.i])

    def generate_json(self, contents: object, attempts: int = 8) -> dict[str, Any]:
        cuota_usadas: set[int] = set()
        last_error: Exception | None = None
        for n in range(attempts):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=JSON_CONFIG,
                )
                text = response.text
                if not text:
                    raise RuntimeError("Gemini no devolvió texto")
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    raise RuntimeError("Gemini no devolvió un objeto JSON")
                return parsed
            except (genai_errors.ServerError, genai_errors.ClientError) as exc:
                last_error = exc
                if es_cuota(exc) and len(self.keys) > 1:
                    cuota_usadas.add(self.i)
                    if len(cuota_usadas) >= len(self.keys):
                        raise
                    self._rotar()
                    while self.i in cuota_usadas:
                        self._rotar()
                    logger.info("Gemini cuota agotada; uso %s", self.label)
                    continue
                if es_demanda(exc) and n < attempts - 1:
                    wait = 15 * (n + 1)
                    logger.info(
                        "Gemini reintento %s/%s en %ss (%s, %s)",
                        n + 1,
                        attempts - 1,
                        wait,
                        _code(exc) or "demanda alta",
                        self.label,
                    )
                    time.sleep(wait)
                    continue
                raise
        raise last_error or RuntimeError("fallo Gemini")


def load_pool() -> GeminiPool:
    keys, model = load_keys()
    pool = GeminiPool(keys, model)
    if len(keys) > 1:
        logger.info("Gemini: %s keys (rota si una se queda sin cuota)", len(keys))
    return pool
