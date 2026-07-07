"""
LLM provider roster + rotation (follow-up to Slice D1/D2, ADR-6).

Generalizes the single-Groq-provider MVP into a round-robin roster across
multiple OpenAI-compatible free-tier APIs (Groq, Cerebras, OpenRouter) with
per-question failover, so no single provider takes 100% of the traffic and a
rate-limited/down provider doesn't send a question straight to the warm
fallback.

Design (sdd/ml-questions-ai/provider-rotation):
- Roster lives in `ml_bot_config` key `llm_providers` — a JSON list of
  `{"name": str, "model": str | null, "enabled": bool}`. `base_url`/API key
  are NEVER stored there — they are resolved from `settings` by `name`
  (secrets stay in `.env`, ADR-4).
- Unknown provider names are skipped with a warning (forward/backward
  compatible with panel edits referencing a provider not yet wired here).
- Malformed roster JSON (bad JSON, not a list, item missing required shape)
  fails safe to a single-item Groq-only roster — the pre-rotation MVP
  behavior — rather than crashing the drafting cycle.
- A provider is AVAILABLE only if `enabled` in the roster AND its API key is
  configured (`is_configured()`), matching each provider's own
  fail-closed contract.
- The rotation cursor is persisted in `ml_bot_config` key
  `llm_rotation_cursor` (same fail-safe int handling as other integer
  config values — malformed/missing -> 0). Round-robin: cursor selects the
  provider that goes FIRST in the per-question try order; every question
  consumes and advances the cursor once, regardless of whether the first
  provider ultimately answers or a later one in the failover chain does.
- Failover: `RotatingProvider.complete()` tries the rotation-ordered
  providers in sequence, at most one full cycle through the roster; if all
  raise `LlmProviderError`, the LAST error is re-raised so the caller
  (`drafting_service._draft_one`) routes to the warm fallback exactly as it
  already does for a single-provider failure — never a crash.
- ADR-5 session discipline: the roster + cursor read/advance is its own
  short-lived `get_background_db()` block; NO session is held while any
  provider's HTTP call is in flight.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_bot_config import MlBotConfig
from app.services.ml_questions import policy
from app.services.ml_questions.llm_provider import LlmProviderError, OpenAICompatProvider

logger = logging.getLogger(__name__)

ROSTER_CONFIG_KEY = "llm_providers"
CURSOR_CONFIG_KEY = "llm_rotation_cursor"

# Item #3 (PR de pulido): failover notification throttle — at most one
# notification per FAILED provider per hour (partial failover), or one per
# hour for the whole outage under key suffix "ALL" (total outage, rotation
# cursor-independent) — tracked as an ISO timestamp in `ml_bot_config` under
# this key prefix (fail-safe: a malformed/unreadable timestamp is treated as
# "never notified", never as a crash).
_FAILOVER_NOTIF_KEY_PREFIX = "llm_failover_notified_"
_FAILOVER_NOTIF_THROTTLE = timedelta(hours=1)

# Legacy single-provider config key (Slice D2) — only consulted for the
# fail-safe/default Groq-only roster, to preserve the pre-rotation behavior
# of a panel-edited `llm_model` applying without needing to touch the new
# `llm_providers` roster key.
_LEGACY_MODEL_CONFIG_KEY = "llm_model"


@dataclass(frozen=True)
class _ProviderSpec:
    """Static, non-secret info needed to resolve a roster entry by name."""

    base_url: str
    api_key: Optional[str]
    default_model: str


def _known_provider_specs() -> dict:
    """Resolved fresh (not module-level) so tests that monkeypatch
    `settings.*_API_KEY` see the change without reload gymnastics."""
    return {
        "groq": _ProviderSpec(
            base_url=settings.GROQ_BASE_URL,
            api_key=settings.GROQ_API_KEY,
            default_model="llama-3.3-70b-versatile",
        ),
        "cerebras": _ProviderSpec(
            base_url=settings.CEREBRAS_BASE_URL,
            api_key=settings.CEREBRAS_API_KEY,
            default_model="llama-3.3-70b",
        ),
        # Free-tier, panel-changeable — documented in docs/RUNBOOKS.md §3.
        "openrouter": _ProviderSpec(
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
            default_model="meta-llama/llama-3.3-70b-instruct:free",
        ),
    }


def _default_roster_entries(db: Any) -> List[dict]:
    """Fail-safe default: a single Groq entry, honoring the legacy
    `llm_model` config key exactly like the pre-rotation `_build_default_provider`
    did — used both when `llm_providers` is unset AND when it is malformed."""
    model = policy.get_config(db, _LEGACY_MODEL_CONFIG_KEY, cast=str, default=None)
    return [{"name": "groq", "model": model, "enabled": True}]


def _load_roster_entries(db: Any) -> List[dict]:
    """Read+parse the `llm_providers` roster. Never raises — any malformed
    input fails safe to the single-Groq default roster."""
    raw = policy.get_config(db, ROSTER_CONFIG_KEY, cast=str, default=None)
    if not raw:
        return _default_roster_entries(db)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "ml-bot provider roster: malformed JSON in '%s', falling back to Groq-only default", ROSTER_CONFIG_KEY
        )
        return _default_roster_entries(db)

    if not isinstance(parsed, list) or not parsed:
        logger.warning(
            "ml-bot provider roster: '%s' is not a non-empty list, falling back to Groq-only default", ROSTER_CONFIG_KEY
        )
        return _default_roster_entries(db)

    entries: List[dict] = []
    # Dedupe key is (name, model) — not name alone (item #4, PR de pulido) —
    # so the SAME provider can appear multiple times with DIFFERENT models
    # (e.g. groq/llama-3.3-70b-versatile then groq/llama-3.1-8b-instant as a
    # separate fallback entry, for per-model rate-limit fairness). Two
    # entries for the same provider AND the same model (including two
    # entries both leaving `model` unset/None) are still a true duplicate.
    seen_variants: set = set()
    for item in parsed:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            logger.warning("ml-bot provider roster: skipping malformed entry %r", item)
            continue

        enabled_raw = item.get("enabled", True)
        if not isinstance(enabled_raw, bool):
            logger.warning("ml-bot provider roster: skipping entry %r with non-boolean 'enabled'", item)
            continue

        name = item["name"].strip()
        model = item.get("model") if isinstance(item.get("model"), str) else None
        variant_key = (name, model)
        if variant_key in seen_variants:
            logger.warning(
                "ml-bot provider roster: skipping duplicate entry for provider '%s' model=%r", name, model
            )
            continue
        seen_variants.add(variant_key)

        entries.append(
            {
                "name": name,
                "model": model,
                "enabled": enabled_raw,
            }
        )

    if not entries:
        logger.warning(
            "ml-bot provider roster: no valid entries in '%s', falling back to Groq-only default", ROSTER_CONFIG_KEY
        )
        return _default_roster_entries(db)

    return entries


def _build_provider(entry: dict, specs: dict) -> Optional[OpenAICompatProvider]:
    """Build an `OpenAICompatProvider` for a roster entry, or None if the
    provider `name` is unknown (skipped with a warning)."""
    spec = specs.get(entry["name"])
    if spec is None:
        logger.warning("ml-bot provider roster: skipping unknown provider name '%s'", entry["name"])
        return None
    model = entry.get("model") or spec.default_model
    return OpenAICompatProvider(
        name=entry["name"],
        api_key=spec.api_key,
        base_url=spec.base_url,
        model=model,
    )


def available_providers(db: Any) -> List[OpenAICompatProvider]:
    """Roster entries that are `enabled` AND configured (API key present),
    resolved in roster order (not rotation order)."""
    specs = _known_provider_specs()
    result: List[OpenAICompatProvider] = []
    for entry in _load_roster_entries(db):
        if not entry["enabled"]:
            continue
        provider = _build_provider(entry, specs)
        if provider is not None and provider.is_configured():
            result.append(provider)
    return result


def _get_cursor(db: Any) -> int:
    """Fail-safe int read (same pattern as other `ml_bot_config` int keys —
    missing/malformed -> 0), mirroring `policy.get_config`'s cast contract."""
    row = db.query(MlBotConfig).filter_by(clave=CURSOR_CONFIG_KEY).first()
    if row is None or row.valor is None or row.valor.strip() == "":
        return 0
    try:
        return int(row.valor)
    except ValueError:
        logger.warning("ml-bot provider rotation: malformed cursor value %r, resetting to 0", row.valor)
        return 0


def _upsert_cursor(db: Any, value: int) -> None:
    row = db.query(MlBotConfig).filter_by(clave=CURSOR_CONFIG_KEY).first()
    if row is None:
        db.add(MlBotConfig(clave=CURSOR_CONFIG_KEY, valor=str(value), tipo="string"))
    else:
        row.valor = str(value)


def build_rotation_order() -> List[OpenAICompatProvider]:
    """Read the roster + cursor, advance the cursor by one, and return the
    providers to try for THIS question, starting at the cursor position and
    wrapping around (one full cycle max). Empty list -> no configured
    provider is available at all.

    Its own short-lived `get_background_db()` block (ADR-5) — no session is
    held once this returns, so the caller's HTTP call(s) never overlap a DB
    transaction.
    """
    with get_background_db() as db:
        providers = available_providers(db)
        if not providers:
            return []

        cursor = _get_cursor(db) % len(providers)
        _upsert_cursor(db, (cursor + 1) % len(providers))

    return providers[cursor:] + providers[:cursor]


def _is_throttled(db: Any, throttle_key: str, now: datetime) -> bool:
    """Fail-safe throttle check: a malformed/unreadable timestamp is treated
    as "never notified" (never as a crash) — logs a warning and returns
    not-throttled."""
    last_raw = policy.get_config(db, throttle_key, cast=str, default=None)
    if not last_raw:
        return False
    try:
        last_dt = datetime.fromisoformat(last_raw)
        return (now - last_dt) < _FAILOVER_NOTIF_THROTTLE
    except ValueError:
        logger.warning(
            "ml-bot failover notification: malformed throttle timestamp %r for '%s', notifying anyway",
            last_raw,
            throttle_key,
        )
        return False


def _record_notified(db: Any, throttle_key: str, now: datetime) -> None:
    row = db.query(MlBotConfig).filter_by(clave=throttle_key).first()
    if row is None:
        db.add(MlBotConfig(clave=throttle_key, valor=now.isoformat(), tipo="string"))
    else:
        row.valor = now.isoformat()


def _notify_failover(failed_names: List[str], covered_by: Optional[str]) -> None:
    """Item #3 (PR de pulido): create a notification via pricing's EXISTING
    notification system (`crear_notificaciones_para_permisos`, mirrors the
    compras/matching pattern) when the rotation falls over between
    providers, or when ALL providers fail.

    Throttle keying (fix for the rotation-dependent `failed_names[0]` bug —
    `build_rotation_order` advances the cursor per question, so
    `failed_names[0]` is NOT stable across calls and can't be used as a
    throttle key on its own):

    - Partial failover (`covered_by` is set): throttled PER FAILED
      PROVIDER, independently — each provider name has its own
      `llm_failover_notified_{name}` key/budget. Only the providers that are
      NOT currently throttled are named in the (single) notification sent,
      and only THOSE get their timestamp recorded.
    - Total outage (`covered_by` is None): a single rotation-independent key
      `llm_failover_notified_ALL` throttles the whole outage as one unit
      (1/h), regardless of which provider happened to be tried first.

    Fail-safe: this is best-effort observability, never allowed to break
    the drafting pipeline — any exception here is caught and logged, never
    re-raised (the caller already has its own successful/failed outcome to
    return regardless of whether this notification fires).
    """
    if not failed_names:
        return
    try:
        # Imported locally to avoid a notification-module import at module
        # load time for a code path that only runs on the (hopefully rare)
        # failover branch — mirrors `resolver_usuarios_con_algun_permiso`'s
        # own local import of `PermisosService`.
        from app.models.notificacion import SeveridadNotificacion  # noqa: PLC0415
        from app.services.notificacion_service import crear_notificaciones_para_permisos  # noqa: PLC0415

        now = datetime.now(timezone.utc)

        with get_background_db() as db:
            if covered_by:
                names_to_notify = [
                    name
                    for name in failed_names
                    if not _is_throttled(db, f"{_FAILOVER_NOTIF_KEY_PREFIX}{name}", now)
                ]
                if not names_to_notify:
                    return  # every failed provider is within its own throttle window

                mensaje = (
                    f"Bot ML: el proveedor LLM '{', '.join(names_to_notify)}' falló — "
                    f"failover activo a '{covered_by}'."
                )

                crear_notificaciones_para_permisos(
                    db,
                    permisos_requeridos=["ml_bot.config"],
                    tipo="ml_bot.llm_failover",
                    mensaje=mensaje,
                    severidad=SeveridadNotificacion.WARNING,
                )

                for name in names_to_notify:
                    _record_notified(db, f"{_FAILOVER_NOTIF_KEY_PREFIX}{name}", now)
            else:
                throttle_key = f"{_FAILOVER_NOTIF_KEY_PREFIX}ALL"
                if _is_throttled(db, throttle_key, now):
                    return  # throttled — total outage already notified within the last hour

                mensaje = (
                    f"Bot ML: TODOS los proveedores LLM fallaron ({', '.join(sorted(failed_names))}) "
                    "— las preguntas están recibiendo la respuesta de fallback."
                )

                crear_notificaciones_para_permisos(
                    db,
                    permisos_requeridos=["ml_bot.config"],
                    tipo="ml_bot.llm_failover",
                    mensaje=mensaje,
                    severidad=SeveridadNotificacion.WARNING,
                )

                _record_notified(db, throttle_key, now)
    except Exception:  # noqa: BLE001 — notification is best-effort, must never break drafting.
        logger.warning("ml-bot failover notification: failed to create/throttle notification", exc_info=True)


class RotatingProvider:
    """`LlmProvider`-shaped (duck-typed) wrapper that resolves the roster +
    rotation cursor fresh on every `complete()` call — i.e. rotation/failover
    happens PER QUESTION, not once per drafting cycle (design requirement).
    Built once per cycle by `drafting_service._build_default_provider`, but
    each `.complete()` call independently re-reads the roster/cursor."""

    def __init__(self) -> None:
        # Item #2 (PR de pulido): which roster entry actually produced the
        # LAST successful `complete()` call, as "provider/model" — read by
        # `drafting_service._resolve_provider_label` right after a successful
        # draft to populate `ml_bot_questions.llm_provider`. `None` until the
        # first successful call.
        self.last_used_provider: Optional[str] = None

    def is_configured(self) -> bool:
        with get_background_db() as db:
            return len(available_providers(db)) > 0

    async def complete(self, system_prompt: str, user_payload: str) -> str:
        providers = build_rotation_order()
        if not providers:
            raise LlmProviderError("no configured LLM provider available in the roster")

        last_error: Optional[LlmProviderError] = None
        failed_names: List[str] = []
        for provider in providers:
            try:
                result = await provider.complete(system_prompt, user_payload)
                logger.info("ml-bot drafting: provider '%s' answered", provider.name)
                provider_model = getattr(provider, "model", None)
                self.last_used_provider = f"{provider.name}/{provider_model}" if provider_model else provider.name
                if failed_names:
                    _notify_failover(failed_names, covered_by=provider.name)
                return result
            except LlmProviderError as exc:
                last_error = exc
                failed_names.append(provider.name)
                logger.warning(
                    "ml-bot drafting: provider '%s' failed, trying next in rotation: %s",
                    provider.name,
                    exc,
                )
                continue

        _notify_failover(failed_names, covered_by=None)
        assert last_error is not None
        raise last_error
