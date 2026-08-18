"""Wires the pricing context (`pxq_pricing_context.py`) and shipping
resolution (`pxq_markup.py`, existing) into `calcular_markup_pxq`
(`pxq_markup.py`, existing -- ZERO production callers before this slice) to
compute a per-tier markup for the panel/read path (slice A1).

Never a fabricated number: `calcular_markup_pxq` is called ONLY when BOTH
the pricing context AND the shipping cost resolve. Every other case reports
a reason instead of a number -- `product_data_missing` wins over
`shipping_unavailable` when both are unresolved, because the data problem is
unrelated to fetch timing and more actionable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional

from sqlalchemy.orm import Session

from app.models.ml_pxq_tier import MlPxqTier
from app.services.pricing_calculator import obtener_constantes_pricing
from app.services.pxq_markup import calcular_markup_pxq, resolve_order_cost, resolve_tier_shipping
from app.services.pxq_pricing_context import resolve_pxq_pricing_context

PxqMarkupReason = Literal["shipping_unavailable", "product_data_missing"]


@dataclass(frozen=True)
class TierMarkup:
    """One tier's markup outcome. `reason` is `None` exactly when the
    computation resolved -- `markup`/`limpio`/`comision_total` are set ONLY
    in that case, never partially."""

    tier_id: int
    reason: Optional[PxqMarkupReason]
    markup: Optional[float] = None
    limpio: Optional[float] = None
    comision_total: Optional[float] = None


def markup_resolved(m: TierMarkup) -> bool:
    return m.reason is None


def markup_for_tiers(db: Session, item_id: str) -> Dict[int, TierMarkup]:
    """Computes the markup for every mirrored tier of `item_id` (the MLA).

    The pricing context is resolved ONCE for the whole publication -- all of
    its tiers share the same product/commission context, so this never
    branches per-item; only the per-tier shipping cost varies.

    Tiers are read in `cantidad_minima` order -- same discipline as
    `GET /{item_id}/live` (`pxq.py`): a tier is a QUANTITY THRESHOLD, so a
    response that hands them back in arbitrary row order is a latent defect
    for every consumer.

    Pricing constants (tier brackets, `varios`) are fetched from the DB
    ONCE per call and threaded through as `constantes=` -- never left to
    `calcular_comision_ml_total`/`calcular_limpio`'s hardcoded module
    defaults, which would silently diverge from what the rest of the app
    (`pricing.py`, `productos_pricing.py`) computes for the same product the
    moment an operator edits the constants table.
    """
    tiers = db.query(MlPxqTier).filter(MlPxqTier.item_id == item_id).order_by(MlPxqTier.cantidad_minima).all()
    if not tiers:
        return {}

    context = resolve_pxq_pricing_context(db, item_id)
    # Only fetched when at least one tier could possibly use it -- when the
    # context itself is unresolved, every tier reports product_data_missing
    # regardless, so the query would be pure waste.
    constantes = obtener_constantes_pricing(db) if context is not None else None

    result: Dict[int, TierMarkup] = {}
    for tier in tiers:
        shipping = resolve_tier_shipping(tier)

        # Precedence when both are unresolved: product_data_missing wins --
        # it is unrelated to fetch timing and more actionable than a
        # shipping-availability reason.
        if context is None:
            result[tier.id] = TierMarkup(tier_id=tier.id, reason="product_data_missing")
            continue
        if shipping is None:
            result[tier.id] = TierMarkup(tier_id=tier.id, reason="shipping_unavailable")
            continue

        costo = resolve_order_cost(context.costo_ars, tier.cantidad_minima)
        computed = calcular_markup_pxq(
            precio_unitario=tier.precio_unitario,
            cantidad_minima=tier.cantidad_minima,
            comision_base_pct=context.comision_base_pct,
            iva=context.iva,
            costo=costo,
            shipping=shipping,
            constantes=constantes,
        )
        result[tier.id] = TierMarkup(
            tier_id=tier.id,
            reason=None,
            markup=computed["markup"],
            limpio=computed["limpio"],
            comision_total=computed["comision_total"],
        )

    return result
