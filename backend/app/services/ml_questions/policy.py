"""
Business-hours gate + config accessor for the ML questions bot (Slice B).

Implements design §5 (business-hours gate) and §11 (config accessor
responsibilities, ADR-4): `ml_bot_config` is read LIVE from the DB on every
call — no indefinite in-process cache — so a panel edit to business hours,
operating mode, or wait minutes applies on the very next poll cycle (R-202,
R-901 scenario 3/4).

Spec references:
- R-201: `operating_mode` config key (`off_hours_only` default | `always_on`).
- R-202: business-hours boundary is the half-open interval [start, end) —
  the start time counts as in-hours, the end time counts as off-hours.
- R-203: `wait_minutes_business_hours` optional override, used only in
  `always_on` mode while a question arrives in-hours; falls back to the
  standard `wait_minutes` when unset.

Judgment Day gotcha: `wait_minutes_business_hours` and `ingest_cursor_ts` are
seeded as an empty string `""` (unset sentinel) by the Slice A migration.
`get_config` MUST treat `""` as unset/None BEFORE attempting to cast — casting
`int("")` raises `ValueError`, which would crash the very first always_on read.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Callable, Optional, TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.ml_bot_config import MlBotConfig

T = TypeVar("T")

_OFF_HOURS_ONLY = "off_hours_only"
_ALWAYS_ON = "always_on"

_DEFAULT_TIMEZONE = "America/Argentina/Buenos_Aires"
_DEFAULT_BUSINESS_HOURS_START = "09:00"
_DEFAULT_BUSINESS_HOURS_END = "18:00"
_DEFAULT_BUSINESS_DAYS = "[1,2,3,4,5]"
_DEFAULT_WAIT_MINUTES = 5


def _cast_bool(valor: str) -> bool:
    """Cast a `ml_bot_config.valor` string to bool. Mirrors truthy string convention
    used elsewhere in the config table (tipo='bool')."""
    return valor.strip().lower() in {"true", "1", "yes", "si", "sí"}


def get_config(
    db: Session,
    clave: str,
    cast: Callable[[str], T] = str,
    default: Optional[T] = None,
) -> Optional[T]:
    """Read a single `ml_bot_config` value live from the DB and cast it.

    Treats a missing row OR an empty-string `valor` as unset, returning
    `default` (None unless provided) WITHOUT attempting to cast — this avoids
    `ValueError` on `int("")` for optional keys like `wait_minutes_business_hours`
    and `ingest_cursor_ts` that are seeded empty (Judgment Day finding).
    """
    row = db.query(MlBotConfig).filter_by(clave=clave).first()
    if row is None or row.valor is None or row.valor.strip() == "":
        return default

    if cast is bool:
        return _cast_bool(row.valor)  # type: ignore[return-value]
    return cast(row.valor)


def is_within_business_hours(db: Session, now: datetime) -> bool:
    """Return True if `now` falls within configured business hours/days.

    Boundary rule (R-202): half-open interval [start, end) — `start` is
    inclusive (counts as in-hours), `end` is exclusive (counts as off-hours).

    A naive `now` is localized to the configured timezone (assumed to already
    represent local wall-clock time) rather than treated as UTC, since callers
    in this pipeline (ingestion/drafting loops) work with local business time.
    """
    tz_name = get_config(db, "timezone", cast=str, default=_DEFAULT_TIMEZONE)
    tz = ZoneInfo(tz_name)

    if now.tzinfo is None:
        localized = now.replace(tzinfo=tz)
    else:
        localized = now.astimezone(tz)

    business_days_raw = get_config(db, "business_days", cast=str, default=_DEFAULT_BUSINESS_DAYS)
    business_days = json.loads(business_days_raw)
    if localized.isoweekday() not in business_days:
        return False

    start_raw = get_config(db, "business_hours_start", cast=str, default=_DEFAULT_BUSINESS_HOURS_START)
    end_raw = get_config(db, "business_hours_end", cast=str, default=_DEFAULT_BUSINESS_HOURS_END)
    start_hour, start_minute = (int(part) for part in start_raw.split(":")[:2])
    end_hour, end_minute = (int(part) for part in end_raw.split(":")[:2])

    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute
    now_minutes = localized.hour * 60 + localized.minute

    return start_minutes <= now_minutes < end_minutes


def get_operating_mode(db: Session) -> str:
    """Return the configured `operating_mode` (R-201). Any value other than the
    two recognized modes is treated as `off_hours_only` (safer default: hard
    gate stays active rather than silently opening always-on behavior)."""
    mode = get_config(db, "operating_mode", cast=str, default=_OFF_HOURS_ONLY)
    if mode not in {_OFF_HOURS_ONLY, _ALWAYS_ON}:
        return _OFF_HOURS_ONLY
    return mode


def is_eligible_for_bot(db: Session, now: datetime) -> bool:
    """Operating-mode gate (R-201): decides whether the bot may handle a
    question arriving at `now` at all, BEFORE any drafting/publishing logic
    runs.

    - `off_hours_only` (default): eligible only when `now` is off-hours.
    - `always_on`: always eligible — business hours no longer hard-block the
      bot; they only affect the wait-window override (see `resolve_wait_minutes`).
    """
    mode = get_operating_mode(db)
    if mode == _ALWAYS_ON:
        return True
    return not is_within_business_hours(db, now)


def resolve_wait_minutes(db: Session, now: datetime) -> int:
    """Wait-window selection (R-203).

    In `always_on` mode, while `now` is in-hours, use the configured
    `wait_minutes_business_hours` override IF SET; otherwise (off-hours, or
    `off_hours_only` mode, or the override is unset) use the standard
    `wait_minutes` value.
    """
    standard_wait = get_config(db, "wait_minutes", cast=int, default=_DEFAULT_WAIT_MINUTES)

    mode = get_operating_mode(db)
    if mode == _ALWAYS_ON and is_within_business_hours(db, now):
        override = get_config(db, "wait_minutes_business_hours", cast=int, default=None)
        if override is not None:
            return override

    return standard_wait


# ---------------------------------------------------------------------------
# Denylist validator (R-502) + manipulation-signal detector (R-503/R-504)
# ---------------------------------------------------------------------------

# Price-like patterns: currency symbols/codes near a number, or "N pesos".
_PRICE_PATTERNS = [
    re.compile(r"\$\s?\d"),
    re.compile(r"\b(ars|usd)\s?\$?\s?\d", re.IGNORECASE),
    re.compile(r"\d[\d.,]*\s*pesos\b", re.IGNORECASE),
    re.compile(r"\bcuesta\b.*\d", re.IGNORECASE),
    re.compile(r"\bsale\b.*\d", re.IGNORECASE),
]

# Stock-quantity-like numeric claims: a number followed by unit words.
_STOCK_QUANTITY_PATTERNS = [
    re.compile(r"\b\d+\s+unidades\b", re.IGNORECASE),
    re.compile(r"\bquedan\s+\d+\b", re.IGNORECASE),
    re.compile(r"\btenemos\s+\d+\b", re.IGNORECASE),
]

# Exact-address patterns: street name + number (Av./calle + digits).
_ADDRESS_PATTERNS = [
    re.compile(r"\b(av\.?|avenida|calle)\s+[a-záéíóúñ0-9\s]+\d{2,5}\b", re.IGNORECASE),
]

_DENYLIST_PATTERNS = _PRICE_PATTERNS + _STOCK_QUANTITY_PATTERNS + _ADDRESS_PATTERNS

# Known manipulation/injection signal phrases (R-503), covering direct
# instruction override, jailbreak/role-play framing, and exfiltration probes
# (R-504 adversarial coverage: EN + es-AR variants).
_MANIPULATION_PATTERNS = [
    re.compile(r"ignor[ae]?\s?(a|á)?\s?(all\s)?(previous\s)?instruc", re.IGNORECASE),
    re.compile(r"forget\s+(your|all|previous)\s+instruc", re.IGNORECASE),
    re.compile(r"olvidate\s+de\s+tus\s+reglas", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+an?\s+unrestricted", re.IGNORECASE),
    re.compile(r"actu[aá]\s+como\s+un\s+asistente\s+sin\s+restric", re.IGNORECASE),
    re.compile(r"system\s?prompt", re.IGNORECASE),
    re.compile(r"reveal|revel[aá]", re.IGNORECASE),
    re.compile(r"actual\s+(price|quantity)", re.IGNORECASE),
    re.compile(r"precio\s+exacto", re.IGNORECASE),
    re.compile(r"direcci[oó]n\s+exacta", re.IGNORECASE),
]


def violates_denylist(answer: str) -> bool:
    """R-502: scan a drafted answer for off-policy content — price-like
    numbers, stock-quantity claims, exact-address patterns. Any match rejects
    the draft (caller routes to fallback + sets `injection_flag`)."""
    return any(pattern.search(answer) for pattern in _DENYLIST_PATTERNS)


def detect_manipulation_signal(question_text: str) -> bool:
    """R-503: scan buyer question text for known injection/manipulation
    patterns BEFORE drafting. A match routes directly to the warm fallback
    message without an LLM call (R-503 scenario)."""
    return any(pattern.search(question_text) for pattern in _MANIPULATION_PATTERNS)
