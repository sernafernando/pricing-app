"""Applicable-now rule of a candidate promotion: the ONE predicate behind "hay mejores ofertas".

A candidate counts only when it can be applied right now (owner, 2026-11-13: "no me sirve una promo mejor que voy a
poder aplicar recién en 10 días"):

- its type is writable (``WRITABLE_PROMOTION_TYPES``);
- its ``start_date`` is <= now, or it has none;
- its ``finish_date`` is > now, or it has none;
- a ``SELLER_CAMPAIGN`` is the Premium of the current month (the panel's chooser rule).

Keep in sync with the frontend's ``isApplicableNow`` (pickPonerPreciosPromos.js); both run the shared cases in
``backend/tests/fixtures/candidata_aplicable_cases.json``.

A leaf module on purpose: ``ml_promotions_write_service`` imports ``ml_promotions_hay_mejores``, so the writable
types live here and the write service re-exports them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Mapping, Optional
from zoneinfo import ZoneInfo

# NOTE: PRICE_MATCHING_MELI_ALL is intentionally EXCLUDED from this set
# (ML-autogestionado, not writable by us). Its absence here is what enforces
# the deny (enroll/remove both fail-close on `not in WRITABLE_PROMOTION_TYPES`)
# — never add it, and never use startswith/prefix matching against
# "PRICE_MATCHING" that could accidentally admit it.
WRITABLE_PROMOTION_TYPES = {"SELLER_CAMPAIGN", "DEAL", "SMART", "PRE_NEGOTIATED", "PRICE_MATCHING", "LIGHTNING"}

# The month of a "Premium <mes>" campaign is the operators' month (the panel uses the browser's local month).
_ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

_MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def parse_promo_instant(value: Any, *, end_of_day: bool = False) -> Optional[datetime]:
    """An ML promotion date as an aware instant, or None when missing or unparseable.

    Naive values are taken as UTC (as ``_is_expired_finish_date`` does for the panel). A date-only value is the start
    of that day, or with ``end_of_day`` the start of the next one (a finish date lasts the whole day)."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    except ValueError:
        return None
    if end_of_day and len(text) == 10:
        parsed = parsed + timedelta(days=1)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def nombre_mes_es(now: datetime) -> str:
    """Spanish name of the month of ``now`` in Argentina."""
    return _MONTHS_ES[now.astimezone(_ARGENTINA_TZ).month - 1]


def inicios_de_mes_entre(since: datetime, until: datetime) -> List[datetime]:
    """The starts of an Argentina month in ``(since, until]``: a SELLER_CAMPAIGN's "Premium <mes>" rule changes there
    with no date of the promo crossing, so the time-window recompute treats them as boundaries too."""
    found: List[datetime] = []
    local = since.astimezone(_ARGENTINA_TZ)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while True:
        start = (
            start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        )
        if start > until:
            return found
        if start > since:
            found.append(start)


def es_premium_del_mes(name: Any, now: datetime) -> bool:
    """A SELLER_CAMPAIGN counts only as "Premium <current month>" (the panel's ``isPremiumCurrentMonth``)."""
    text = (name or "").lower() if isinstance(name, str) else ""
    return "premium" in text and nombre_mes_es(now) in text


def candidata_aplicable_ahora(entry: Mapping[str, Any], now: datetime) -> bool:
    """Whether the candidate ``entry`` (a raw seller-promotions entry) can be applied at ``now`` (aware)."""
    promo_type = entry.get("type") or entry.get("promotion_type")
    if promo_type not in WRITABLE_PROMOTION_TYPES:
        return False
    start = parse_promo_instant(entry.get("start_date"))
    if start is not None and start > now:
        return False
    finish = parse_promo_instant(entry.get("finish_date"), end_of_day=True)
    if finish is not None and finish <= now:
        return False
    if promo_type == "SELLER_CAMPAIGN" and not es_premium_del_mes(entry.get("name"), now):
        return False
    return True
