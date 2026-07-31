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
shipping cost. It does not import `ProductoPricing` and must never do so —
PxQ tiers are additional quantity prices on top of the base price, and this
boundary is enforced by a dedicated AST import-scan test.
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
Money = Union[float, int, Decimal]


def _as_float(value: Money) -> float:
    return float(value)


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
    costo_envio_total = getattr(tier, "costo_envio_total", None)
    if costo_envio_total is None:
        return None
    return ShipmentShippingCost(amount=float(costo_envio_total))


def calcular_markup_pxq(
    precio_unitario: Money,
    cantidad_minima: int,
    comision_base_pct: float,
    iva: float,
    costo: Money,
    shipping: ShipmentShippingCost,
    db: Optional[Any] = None,
    constantes: Optional[Dict] = None,
    grupo_id: Optional[int] = None,
) -> Dict[str, float]:
    """Quantity-aware markup wrapper for a PxQ tier.

    Reuses `calcular_comision_ml_total` / `calcular_limpio` UNCHANGED,
    feeding them the ORDER TOTAL (`precio_unitario * cantidad_minima`)
    instead of the unit price, and the whole-shipment shipping cost instead
    of a single unit's `costo_envio`.

    `shipping` has NO default: a caller holding only a bare float cannot
    call this function without going through `resolve_tier_shipping` first,
    making the forbidden silent per-unit fallback structurally impossible
    rather than merely discouraged.
    """
    precio_total = _as_float(precio_unitario) * cantidad_minima
    costo_float = _as_float(costo)

    comisiones = calcular_comision_ml_total(precio_total, comision_base_pct, iva, db=db, constantes=constantes)
    limpio = calcular_limpio(
        precio_total,
        iva,
        shipping.amount,
        comisiones["comision_total"],
        db=db,
        constantes=constantes,
        grupo_id=grupo_id,
    )
    markup = calcular_markup(limpio, costo_float)

    return {
        "precio_total": precio_total,
        "comision_total": comisiones["comision_total"],
        "limpio": limpio,
        "markup": markup,
    }
