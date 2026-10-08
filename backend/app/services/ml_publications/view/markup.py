"""Markup of ONE publication unit, with the Productos maths (pure).

`unit_markup` prices a Mercado Libre publication at its current price on the list
ML charges it (`pricelist_resolver`), through the very same pure functions the
Productos listing calls, in the same order and with the same `constantes`:
commission lookup (`PricingContext.comision`), `calcular_comision_ml_total`,
`resolve_envio`, `calcular_limpio`, `calcular_markup`. There is no parallel
formula here.

Two rules that differ from Productos on purpose:

* No cost means no markup. `calcular_markup` returns 0 when the cost is 0, which
  would read as "break even"; a publication without a usable cost answers
  `None` with reason `sin_costo`.
* The shipping cost is always resolved first (`resolve_envio`) and handed to
  `calcular_limpio` already resolved; `db` is never passed, so nothing here can
  open a query.

The caller extracts `UnitInputs` (SQL) and the real shipping costs
(`envio_real_by_item`, one batch per request); this module does no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from app.services.ml_publications.pricelist_resolver import resolve_pricelist
from app.services.pricing_calculator import calcular_comision_ml_total, calcular_limpio, calcular_markup
from app.services.pricing_columns import campo_for_pricelist
from app.services.pricing_context import PricingContext, resolve_envio

REASON_OK = "ok"
REASON_SIN_VINCULO = "sin_vinculo"
REASON_SIN_COSTO = "sin_costo"
REASON_SIN_COMISION = "sin_comision"
REASON_SIN_PRECIO = "sin_precio"
REASON_ADS_SIN_VENTAS = "ads_sin_ventas"  # Ads cost but no units sold: no per-unit cost to apply

SOURCE_SALE_PRICE = "sale_price"
SOURCE_ITEM_PRICE = "item_price"
SOURCE_PRODUCTOS_FALLBACK = "productos_fallback"


@dataclass(frozen=True)
class UnitInputs:
    """Everything `unit_markup` needs about one publication unit, already extracted."""

    item_id: str
    listing_type_id: Optional[str]
    tags: Sequence[str]
    sale_terms_campaign: Optional[str]
    sale_price: Optional[float]  # fetched `sale_price.amount`; None when absent or failed
    item_price: Optional[float]  # `ml_items.price`
    # `ProductoPricing` price columns of the linked product, keyed by column name.
    fallback_prices: Mapping[str, Optional[float]] = field(default_factory=dict)
    # Linked catalog product; `producto_item_id` None means "no link".
    producto_item_id: Optional[int] = None
    costo: Optional[float] = None
    moneda_costo: Optional[str] = None
    iva: float = 21.0
    envio: Optional[float] = None
    subcategoria_id: Optional[int] = None


@dataclass(frozen=True)
class UnitMarkup:
    value: Optional[float]  # percent; None whenever it cannot be computed (never 0 for "unknown")
    reason: str
    limpio: Optional[float]
    costo_ars: Optional[float]
    price: Optional[float]
    source: Optional[str]
    pricelist_id: Optional[int]


def _unusable(reason: str, *, pricelist_id: Optional[int] = None) -> UnitMarkup:
    return UnitMarkup(None, reason, None, None, None, None, pricelist_id)


def _positive(value: Optional[float]) -> bool:
    return value is not None and value > 0


def _pick_price(inputs: UnitInputs, pricelist_id: int) -> tuple[Optional[float], Optional[str]]:
    """sale_price > item_price > Productos price of the resolved list > nothing."""
    if _positive(inputs.sale_price):
        return float(inputs.sale_price), SOURCE_SALE_PRICE
    if _positive(inputs.item_price):
        return float(inputs.item_price), SOURCE_ITEM_PRICE
    campo = campo_for_pricelist(pricelist_id)
    fallback = inputs.fallback_prices.get(campo) if campo else None
    if _positive(fallback):
        return float(fallback), SOURCE_PRODUCTOS_FALLBACK
    return None, None


def unit_markup(ctx: PricingContext, inputs: UnitInputs, envio: Mapping[int, float]) -> UnitMarkup:
    """Markup (percent) of one publication unit.

    `envio` is `envio_real_by_item` (real shipping cost by the linked product's `item_id`),
    the mapping `resolve_envio` consumes.
    """
    if inputs.producto_item_id is None:
        return _unusable(REASON_SIN_VINCULO)
    if not _positive(inputs.costo):
        return _unusable(REASON_SIN_COSTO)

    resolution = resolve_pricelist(inputs.listing_type_id, inputs.tags, inputs.sale_terms_campaign)
    if resolution.pricelist_id is None:
        return _unusable(resolution.reason)
    pricelist_id = resolution.pricelist_id

    grupo_id = ctx.grupo_of(inputs.subcategoria_id)
    comision_base = ctx.comision(pricelist_id, grupo_id)
    if not comision_base:
        return _unusable(REASON_SIN_COMISION, pricelist_id=pricelist_id)

    price, source = _pick_price(inputs, pricelist_id)
    if price is None:
        return _unusable(REASON_SIN_PRECIO, pricelist_id=pricelist_id)

    costo_ars = ctx.costo_en_pesos(inputs.costo, inputs.moneda_costo)
    comisiones = calcular_comision_ml_total(price, comision_base, inputs.iva, constantes=ctx.constantes)
    costo_envio = resolve_envio(ctx, envio, inputs.producto_item_id, inputs.envio or 0, grupo_id, price)
    limpio = calcular_limpio(price, inputs.iva, costo_envio, comisiones["comision_total"], constantes=ctx.constantes)
    # costo_ars > 0 here (costo was checked and conversion only multiplies), so the
    # `calcular_markup` zero-cost branch cannot be reached.
    value = calcular_markup(limpio, costo_ars) * 100
    return UnitMarkup(value, REASON_OK, limpio, costo_ars, price, source, pricelist_id)


@dataclass(frozen=True)
class PublicationMarkup:
    """Markup of a whole publication: one resolved `UnitMarkup` per variation plus the summary.

    `worst` (the lowest value) drives sorting and `any_negative` drives the negative filter
    (addendum decision 5). `partial` counts variations without a value when at least one has one.
    """

    variations: tuple[UnitMarkup, ...]
    value_min: Optional[float]
    value_max: Optional[float]
    worst: Optional[float]
    any_negative: bool
    partial: int
    reason: str

    @property
    def is_range(self) -> bool:
        return self.value_min is not None and self.value_min != self.value_max


def summarize(variations: Sequence[UnitMarkup]) -> PublicationMarkup:
    """Range, worst and any-negative over the variations that have a value."""
    values = [v.value for v in variations if v.value is not None]
    if not values:
        concrete = [v.reason for v in variations if v.reason != REASON_SIN_VINCULO]
        return PublicationMarkup(
            tuple(variations), None, None, None, False, 0, concrete[0] if concrete else REASON_SIN_VINCULO
        )
    return PublicationMarkup(
        tuple(variations),
        min(values),
        max(values),
        min(values),
        any(v < 0 for v in values),
        len(variations) - len(values),
        REASON_OK,
    )


def aggregate_publication(
    item_unit: Optional[UnitMarkup], variation_units: Sequence[Optional[UnitMarkup]]
) -> PublicationMarkup:
    """Aggregate the variations of one publication.

    `item_unit` is the item-level unit (variation 0) and `variation_units` one entry per variation
    (`None` when that variation has no link of its own). A variation without its own unit falls
    back to the item-level one, else it is `sin_vinculo`. With no variations the item-level unit is
    the whole publication.
    """
    unlinked = _unusable(REASON_SIN_VINCULO)
    if not variation_units:
        return summarize([item_unit or unlinked])
    return summarize([own or item_unit or unlinked for own in variation_units])
