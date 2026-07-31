"""Quantity-aware markup for MercadoLibre PxQ (wholesale, price-by-quantity)
tiers.

MercadoLibre evaluates the low-price fixed charge (the tier bracket inside
`calcular_comision_ml_total`) on the ORDER TOTAL, not the unit price — a
30-unit order at $500/unit ($15,000 total) does not pay the same fixed
charge as a single $500 unit. The existing bracket logic in
`pricing_calculator.py` is therefore already correct once it is fed the
order total; the only historical defect was `calcular_limpio` subtracting a
SINGLE unit's `costo_envio` for an N-unit order instead of the whole
shipment's cost.

This module fixes that by construction: it wraps
`calcular_comision_ml_total` / `calcular_limpio` (never modifying them) and
feeds them `precio_unitario * cantidad_minima` and the WHOLE-SHIPMENT
shipping cost.

It does not reference `ProductoPricing` DIRECTLY, and the AST import-scan
test enforces exactly that and no more. The boundary is not transitive:
`pricing_calculator` itself imports `ProductoPricing` for the base-price
markup helpers, and closing that transitively would mean forking the pricing
chain — the opposite of this module's whole point. What the scan buys is that
no PxQ module reaches for the base-price table on its own; the guarantee that
nothing WRITES to `productos_pricing` is the runtime assert on the session,
which arrives with the write path.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Union

from app.services.pricing_calculator import (
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
)

# A tier's monetary columns are `Numeric(14, 2)`, so a real row hands over
# `Decimal`, while the pricing chain multiplies against float constants
# (`/ 1.21`, tier thresholds). Mixing the two raises TypeError at runtime, and
# no test using float literals will ever catch it. Every monetary value that
# can originate from a database column is normalized at this boundary — the
# same treatment `resolve_tier_shipping` already gave the shipping cost.
#
# KNOWN LIMITATION, not a preference: converting to float degrades decimal
# money to binary. It is forced by `pricing_calculator`, which is float
# throughout and which this module deliberately does not modify — one formula,
# one source of truth. `pxq_tier_service` keeps Decimal on the STORAGE side, so
# what is persisted stays exact; only the derived markup carries float error.
# Moving the pricing chain to Decimal is the real fix and is out of scope here.
Money = Union[float, int, Decimal]


def _as_float(value: Money) -> float:
    return float(value)


# Distinguishes "this object has no such attribute" from "the attribute is
# there and still empty". Collapsing the two would report a mistyped object as
# a tier the user merely has not finished filling in.
_MISSING = object()


@dataclass(frozen=True)
class ShipmentShippingCost:
    """Whole-shipment shipping cost for an N-unit PxQ tier order.

    The ONLY producer of this type is `resolve_tier_shipping`. A caller
    holding only a bare float (e.g. a product's per-unit `envio` field)
    cannot construct or substitute one — there is no implicit conversion
    and no default anywhere downstream to fall through to.
    """

    amount: float


def resolve_tier_shipping(tier: Any) -> Optional[ShipmentShippingCost]:
    """Build the whole-shipment shipping cost for a PxQ tier.

    Reads ONLY `tier.costo_envio_total` — there is no fallback to any
    per-unit shipping field. Returns `None` when the tier isn't ready to be
    priced (`costo_envio_total` not yet set); callers MUST treat that as
    `estado='incompleto'` and never price or write the tier.
    """
    costo_envio_total = getattr(tier, "costo_envio_total", _MISSING)
    if costo_envio_total is _MISSING:
        # A tier that has never carried this attribute is not an incomplete
        # tier — it is the wrong object. Returning None would surface as rows
        # stuck on `incompleto` forever with nothing explaining why.
        raise TypeError(f"expected a PxQ tier with `costo_envio_total`, got {type(tier).__name__}")
    if costo_envio_total is None:
        return None
    return ShipmentShippingCost(amount=float(costo_envio_total))


@dataclass(frozen=True)
class OrderCost:
    """Cost of the WHOLE N-unit order, not of one unit.

    `calcular_markup` divides the order-level `limpio` by whatever it is
    handed, so a per-unit cost inflates the markup by a factor of N — the same
    unit-vs-order confusion this module exists to eliminate on the shipping
    side. A bare float carries no unit, and `costo` is the one input a caller
    is most likely to reach for from `producto.costo`, which IS per-unit.

    So it gets the same treatment shipping got: one producer,
    `resolve_order_cost`, which requires the quantity and does the
    multiplication itself. There is no way to hand over a per-unit figure and
    have it silently accepted.
    """

    amount: float


def resolve_order_cost(costo_unitario: Money, cantidad_minima: int) -> OrderCost:
    """Scale a PER-UNIT cost to the whole order."""
    return OrderCost(amount=_as_float(costo_unitario) * cantidad_minima)


def calcular_markup_pxq(
    precio_unitario: Money,
    cantidad_minima: int,
    comision_base_pct: float,
    iva: float,
    costo: OrderCost,
    shipping: ShipmentShippingCost,
    db: Optional[Any] = None,
    constantes: Optional[Dict] = None,
) -> Dict[str, float]:
    """Quantity-aware markup wrapper for a PxQ tier.

    Reuses `calcular_comision_ml_total` / `calcular_limpio` UNCHANGED,
    feeding them the ORDER TOTAL (`precio_unitario * cantidad_minima`)
    instead of the unit price, and the whole-shipment shipping cost instead
    of a single unit's `costo_envio`.

    `shipping` has NO default: a caller holding only a bare float cannot
    call this function without going through `resolve_tier_shipping` first,
    making the forbidden silent per-unit fallback structurally impossible
    rather than merely discouraged. `grupo_id` is deliberately absent from
    the signature for the same reason — see the call below.

    `costo` is an `OrderCost`, never a bare number: it must be the cost of all
    `cantidad_minima` units, because `limpio` is the net of the whole order.
    Handing over one unit's cost would inflate the markup by a factor of N.
    """
    precio_total = _as_float(precio_unitario) * cantidad_minima

    comisiones = calcular_comision_ml_total(precio_total, comision_base_pct, iva, db=db, constantes=constantes)
    limpio = calcular_limpio(
        precio_total,
        iva,
        shipping.amount,
        comisiones["comision_total"],
        db=db,
        constantes=constantes,
        # grupo_id stays None, deliberately. `calcular_limpio` replaces a zero
        # `costo_envio` with the group's PER-UNIT average when given one, which
        # is the exact fallback this module exists to prevent — and a tier may
        # legitimately carry a zero whole-shipment cost. Not passing it is what
        # makes the fallback unreachable rather than merely discouraged.
        grupo_id=None,
    )
    markup = calcular_markup(limpio, costo.amount)

    return {
        "precio_total": precio_total,
        "comision_total": comisiones["comision_total"],
        "limpio": limpio,
        "markup": markup,
    }
