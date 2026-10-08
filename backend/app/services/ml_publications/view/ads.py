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
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Optional, Protocol, Sequence

from app.services.ml_publications.view.markup import (
    REASON_ADS_SIN_VENTAS,
    REASON_SIN_COSTO,
    PublicationMarkup,
    UnitMarkup,
    summarize,
)

STATE_OK = "ok"
STATE_SIN_COSTO = "sin_costo"
STATE_ADS_SIN_VENTAS = REASON_ADS_SIN_VENTAS


class AdsAvailability(enum.Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class AdsCostProvider(Protocol):
    """Source of the Ads cost per MLA, already net of IVA."""

    def availability(self) -> AdsAvailability: ...

    def amounts(self, mla_ids: Sequence[str]) -> Mapping[str, float]:
        """Ads cost of the period by MLA; an MLA without Ads cost is absent."""
        ...


# ponytail: stub provider — replace with the ml-billing-balance provider when billing is wired
class UnavailableAdsProvider:
    """The provider until the billing source is wired: no data, never an error."""

    def availability(self) -> AdsAvailability:
        return AdsAvailability.UNAVAILABLE

    def amounts(self, mla_ids: Sequence[str]) -> Mapping[str, float]:
        return {}


def get_ads_provider() -> AdsCostProvider:
    """FastAPI dependency; replaced when the billing provider lands."""
    return UnavailableAdsProvider()


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
