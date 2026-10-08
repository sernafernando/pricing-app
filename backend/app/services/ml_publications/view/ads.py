"""Ads (Product Ads) cost applied to the publication markup (pure).

Addendum decisions 3, 5 and 6:

* The provider's cost (`ml-billing-balance`) is already net of IVA. It is used AS IS: nothing in
  this module converts it, so IVA can never be subtracted twice.
* The cost is per publication. Spread over the units sold in the period it gives ONE per-unit
  value, applied identically to every variation of the publication.
* Without units sold there is no per-unit cost: the state is `ads_sin_ventas`, the markup has no
  value and the amount is kept for display.
* The formula is configurable (`ML_PUB_VIEW_ADS_FORMULA`); the name must be a key of
  `ADS_MARKUP_FORMULAS`.

No I/O: the provider is a Protocol; the only implementation today says "unavailable".
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, replace
from datetime import date
from typing import Callable, Mapping, Optional, Protocol, Sequence

from app.services.ml_publications.view.markup import (
    REASON_ADS_SIN_VENTAS,
    REASON_SIN_COSTO,
    PublicationMarkup,
    UnitMarkup,
    summarize,
)

logger = logging.getLogger(__name__)

STATE_OK = "ok"
STATE_SIN_COSTO = "sin_costo"
STATE_ADS_SIN_VENTAS = REASON_ADS_SIN_VENTAS


class AdsAvailability(enum.Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class AdsCostProvider(Protocol):
    """Source of the Ads cost per MLA, already net of IVA."""

    def availability(self) -> AdsAvailability: ...

    def amounts(self, mla_ids: Optional[Sequence[str]], date_from: date, date_to: date) -> Mapping[str, float]:
        """Ads cost by MLA over the business days `[date_from, date_to]`; an MLA without Ads cost is absent.
        `mla_ids=None` means every MLA that has cost in the period (the set-wide sort)."""
        ...


# ponytail: stub provider — replace with the ml-billing-balance provider when billing is wired
class UnavailableAdsProvider:
    """The provider until the billing source is wired: no data, never an error."""

    def availability(self) -> AdsAvailability:
        return AdsAvailability.UNAVAILABLE

    def amounts(self, mla_ids: Optional[Sequence[str]], date_from: date, date_to: date) -> Mapping[str, float]:
        return {}


def get_ads_provider() -> AdsCostProvider:
    """FastAPI dependency; replaced when the billing provider lands."""
    return UnavailableAdsProvider()


REASON_PROVIDER_MISSING = "provider_missing"
REASON_PROVIDER_ERROR = "provider_error"
REASON_OK = "ok"


@dataclass(frozen=True)
class AdsStatus:
    """The `ads` block of a response: whether Ads data exists, whether this request asked for it and whether it
    was actually applied (only when it exists, was asked for and the period is known). The period the client
    sent is echoed whether or not Ads could be applied."""

    available: bool
    reason: str
    requested: bool
    applied: bool
    date_from: Optional[date] = None
    date_to: Optional[date] = None

    def degraded(self) -> "AdsStatus":
        """The status after the provider failed while it was being used: nothing was applied."""
        return AdsStatus(False, REASON_PROVIDER_ERROR, self.requested, False, self.date_from, self.date_to)


def resolve_ads(
    provider: AdsCostProvider, *, requested: bool, date_from: Optional[date], date_to: Optional[date]
) -> AdsStatus:
    """Ask the provider if it can serve Ads and decide whether this request applies it. A provider that raises is
    a provider that is not there: the answer degrades, the request never fails because of Ads."""
    try:
        availability = provider.availability()
    except Exception:
        logger.warning("ads provider availability failed", exc_info=True)
        return AdsStatus(False, REASON_PROVIDER_ERROR, requested, False, date_from, date_to)
    if availability is not AdsAvailability.AVAILABLE:
        return AdsStatus(False, REASON_PROVIDER_MISSING, requested, False, date_from, date_to)
    applied = requested and date_from is not None and date_to is not None
    return AdsStatus(True, REASON_OK, requested, applied, date_from, date_to)


def _costo_extra(limpio: float, costo: float, per_unit: float) -> Optional[float]:
    """`limpio / (costo + ads_por_unidad) - 1`, in percent."""
    denominator = costo + per_unit
    if denominator <= 0:
        return None
    return (limpio / denominator - 1) * 100


def _resta_limpio(limpio: float, costo: float, per_unit: float) -> Optional[float]:
    """`(limpio - ads_por_unidad) / costo - 1`, in percent."""
    if costo <= 0:
        return None
    return ((limpio - per_unit) / costo - 1) * 100


ADS_MARKUP_FORMULAS: Mapping[str, Callable[[float, float, float], Optional[float]]] = {
    "costo_extra": _costo_extra,
    "resta_limpio": _resta_limpio,
}


@dataclass(frozen=True)
class AdsRow:
    amount: Optional[float]
    units: Optional[int]
    per_unit: Optional[float]  # None unless state is ok (0.0 for sin_costo)
    state: str


def ads_row(amount: Optional[float], units: Optional[int]) -> AdsRow:
    """Ads figures of one publication; `amount` is used verbatim (already net of IVA)."""
    if amount is None or amount <= 0:
        return AdsRow(amount, units, 0.0, STATE_SIN_COSTO)
    if units is None or units <= 0:
        return AdsRow(amount, units, None, STATE_ADS_SIN_VENTAS)
    return AdsRow(amount, units, amount / units, STATE_OK)


@dataclass(frozen=True)
class AdsApplied:
    markup: PublicationMarkup
    state: str
    amount: Optional[float]
    per_unit: Optional[float]


def _apply_to_unit(
    unit: UnitMarkup, formula: Callable[[float, float, float], Optional[float]], per_unit: float
) -> UnitMarkup:
    if unit.value is None or unit.limpio is None or unit.costo_ars is None:
        return unit
    value = formula(unit.limpio, unit.costo_ars, per_unit)
    if value is None:
        return replace(unit, value=None, reason=REASON_SIN_COSTO)
    return replace(unit, value=value)


def apply_ads(publication_markup: PublicationMarkup, row: AdsRow, formula: str) -> AdsApplied:
    """Markup after Ads; `formula` is the `ML_PUB_VIEW_ADS_FORMULA` setting.

    Without Ads cost the plain markup is returned untouched.
    """
    if formula not in ADS_MARKUP_FORMULAS:
        raise ValueError(f"unknown ads formula {formula!r}")
    if row.state == STATE_SIN_COSTO:
        return AdsApplied(publication_markup, row.state, row.amount, row.per_unit)
    if row.state == STATE_ADS_SIN_VENTAS:
        # Only variations that had a value lose it; an unusable one keeps its own reason.
        blank = tuple(
            replace(v, value=None, reason=REASON_ADS_SIN_VENTAS) if v.value is not None else v
            for v in publication_markup.variations
        )
        blanked = summarize(blank)
        if publication_markup.worst is not None:
            blanked = replace(blanked, reason=REASON_ADS_SIN_VENTAS)
        return AdsApplied(blanked, row.state, row.amount, None)
    function = ADS_MARKUP_FORMULAS[formula]
    adjusted = tuple(_apply_to_unit(v, function, row.per_unit) for v in publication_markup.variations)
    return AdsApplied(summarize(adjusted), row.state, row.amount, row.per_unit)
