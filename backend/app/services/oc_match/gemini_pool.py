"""Three-key Gemini pool. 429 rotates keys then fallback-once; 503 short-sleeps then rotates. Never logs API keys."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
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

DEMANDA_SLEEPS: tuple[int, int] = (5, 10)
_DEFAULT_MODEL = "gemini-3.5-flash-lite"


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
    model = (settings.GEMINI_MODEL or _DEFAULT_MODEL).strip()
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
    def __init__(self, keys: list[str], model: str, fallback_model: str | None = None) -> None:
        if not keys:
            raise MissingGeminiKeysError("Falta GEMINI_API_KEY (o GEMINI_API_KEY_2 / _3)")
        self.keys = keys
        self.model = model
        resolved = (fallback_model or "").strip()
        self.fallback_model = None if (not resolved or resolved == model) else resolved
        self.en_fallback = False
        self.i = 0
        self.client = genai.Client(api_key=keys[0])

    @property
    def label(self) -> str:
        return f"model={self.model} key {self.i + 1}/{len(self.keys)}"

    def _rotar(self) -> None:
        self.i = (self.i + 1) % len(self.keys)
        self.client = genai.Client(api_key=self.keys[self.i])

    def _cambiar_a_fallback(
        self,
        cuota_usadas: set[int],
        demanda_vistas: set[int],
        demanda_sleeps: dict[int, int],
    ) -> bool:
        if self.en_fallback or not self.fallback_model:
            return False
        self.model = self.fallback_model
        self.en_fallback = True
        self.i = 0
        self.client = genai.Client(api_key=self.keys[0])
        cuota_usadas.clear()
        demanda_vistas.clear()
        demanda_sleeps.clear()
        return True

    def generate_json(
        self,
        contents: object,
        attempts: int = 12,
        transform_text: Callable[[str], str] | None = None,
    ) -> dict[str, Any]:
        cuota_usadas: set[int] = set()
        demanda_vistas: set[int] = set()
        demanda_sleeps: dict[int, int] = {}
        last_error: Exception | None = None
        attempt = 0
        while attempt < attempts:
            attempt += 1
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=JSON_CONFIG,
                )
                text = response.text
                if not text:
                    raise RuntimeError("Gemini no devolvió texto")
                if transform_text is not None:
                    text = transform_text(text)
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Gemini devolvió JSON malformado") from exc
                if not isinstance(parsed, dict):
                    raise RuntimeError("Gemini no devolvió un objeto JSON")
                return parsed
            except (genai_errors.ServerError, genai_errors.ClientError) as exc:
                last_error = exc
                if es_cuota(exc):
                    cuota_usadas.add(self.i)
                    if len(cuota_usadas) >= len(self.keys):
                        if self._cambiar_a_fallback(cuota_usadas, demanda_vistas, demanda_sleeps):
                            logger.info("Gemini fallback; uso %s", self.label)
                            if attempt >= attempts:
                                attempt = attempts - 1
                            continue
                        logger.warning("Gemini cuota agotada %s", self.label)
                        raise
                    self._rotar()
                    while self.i in cuota_usadas:
                        self._rotar()
                    logger.info("Gemini cuota agotada; uso %s", self.label)
                    continue
                if es_demanda(exc):
                    demanda_vistas.add(self.i)
                    all_seen = len(demanda_vistas) >= len(self.keys)
                    budget_done = attempt >= attempts
                    if all_seen or budget_done:
                        if self._cambiar_a_fallback(cuota_usadas, demanda_vistas, demanda_sleeps):
                            logger.info("Gemini fallback; uso %s", self.label)
                            if attempt >= attempts:
                                attempt = attempts - 1
                            continue
                        logger.warning("Gemini demanda agotada %s", self.label)
                        raise
                    sleeps_used = demanda_sleeps.get(self.i, 0)
                    if sleeps_used < len(DEMANDA_SLEEPS):
                        wait = DEMANDA_SLEEPS[sleeps_used]
                        demanda_sleeps[self.i] = sleeps_used + 1
                        logger.info(
                            "Gemini reintento %s/%s en %ss (%s, %s)",
                            sleeps_used + 1,
                            len(DEMANDA_SLEEPS),
                            wait,
                            _code(exc) or "demanda alta",
                            self.label,
                        )
                        time.sleep(wait)
                        continue
                    self._rotar()
                    while self.i in demanda_vistas:
                        self._rotar()
                    logger.info("Gemini demanda; uso %s", self.label)
                    continue
                raise
        raise last_error or RuntimeError("fallo Gemini")


def load_pool() -> GeminiPool:
    keys, model = load_keys()
    raw_fb = (getattr(settings, "GEMINI_MODEL_FALLBACK", None) or "").strip()
    fallback: str | None = None if (not raw_fb or raw_fb == model) else raw_fb
    pool = GeminiPool(keys, model, fallback)
    if pool.fallback_model is None:
        logger.info("Gemini: %s keys model=%s fallback=disabled", len(keys), model)
    else:
        logger.info("Gemini: %s keys model=%s fallback=%s", len(keys), model, pool.fallback_model)
    return pool
