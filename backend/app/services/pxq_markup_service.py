"""Wires the pricing context (`pxq_pricing_context.py`) and shipping
resolution (`pxq_markup.py`, existing) into `calcular_markup_pxq`
(`pxq_markup.py`, existing -- ZERO production callers before this slice) to
compute a per-tier markup for the panel/read path (slice A1).

Never a fabricated number: `calcular_markup_pxq` is called ONLY when BOTH
the pricing context AND the shipping cost resolve. Every other case reports
a reason instead of a number -- `product_data_missing` wins over
`shipping_unavailable` when both are unresolved, because the data problem is
unrelated to fetch timing and more actionable.

`markup_for_tiers` itself is a PURE DB READ (slice A1 invariant, restored by
slice B's pool-safety fix below) -- it never calls the ml-webhook proxy and
never holds a session across a network call. The TTL-gated shipping
auto-fetch lives in the SEPARATE `refresh_stale_tier_shipping`, which owns
its own short sessions end-to-end and is invoked by CALLERS
(`routers/pxq.py`'s `obtener_markup_pxq`, `ml_pxq_write_service.sync_pxq_tiers`)
BEFORE they touch their own session for the actual markup read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Literal, Optional

from sqlalchemy.orm import Session

from app.core.database import get_background_db
from app.models.ml_pxq_tier import MlPxqTier
from app.services.ml_webhook_client import ml_webhook_client
from app.services.pricing_calculator import obtener_constantes_pricing
from app.services.pxq_markup import calcular_markup_pxq, resolve_order_cost, resolve_tier_shipping
from app.services.pxq_pricing_context import resolve_pxq_pricing_context
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

PxqMarkupReason = Literal["shipping_unavailable", "product_data_missing"]

# 24h TTL, slice B design. Anything fresher than this makes ZERO calls to the
# ml-webhook proxy; NULL (never fetched) or older always calls it.
_SHIPPING_TTL = timedelta(hours=24)


def _is_stale(fetched_at: Optional[datetime]) -> bool:
    if fetched_at is None:
        return True
    if fetched_at.tzinfo is None:
        # SQLite loses tzinfo after flush/refresh (documented repo trap) --
        # values written by THIS module are always tz-aware, so a naive
        # value here can only originate from that round-trip and is safely
        # reinterpreted as UTC, never a different zone.
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - fetched_at >= _SHIPPING_TTL


@dataclass(frozen=True)
class _StaleTierRef:
    """Flat, session-free snapshot of one tier that needs a shipping
    re-fetch -- the ONLY thing carried across the network-call phase, so
    that phase never needs (and never gets) a live ORM object or session."""

    tier_id: int
    item_id: str
    cantidad_minima: int
    precio_unitario: Decimal


def refresh_stale_tier_shipping(item_id: str) -> None:
    """TTL-gated auto-fetch orchestrator for `item_id`'s PxQ tiers (slice B,
    pool-safety fix). Called by READ-PATH CALLERS -- `obtener_markup_pxq`
    (`routers/pxq.py`) and `sync_pxq_tiers`
    (`ml_pxq_write_service.py`, via its own `markup_for_tiers` gate) --
    BEFORE they touch their own session for the actual markup read.

    Three isolated phases, matching PR #811's short-block discipline (the
    QueuePool-exhaustion fix this repo already shipped once):

      (a) One SHORT session (`get_background_db`) reads which tiers are
          stale into flat `_StaleTierRef`s, then closes.
      (b) N sequential proxy fetches run with NO session open anywhere --
          not this function's, and NOT the caller's, because this function
          never receives or touches the caller's session at all.
      (c) A SECOND short session persists every SUCCESSFUL fetch (value +
          stamp together, same D3 "freshness of the VALUE" contract
          `pxq_tier_service.update_pxq_tier`'s manual-write path uses) in
          ONE commit, then closes.

    NEVER touches, commits, or closes a caller-supplied `Session` -- the
    caller's own unit of work (e.g. `sync_pxq_tiers`'s D6 business commit)
    stays exactly as ordered as before this function existed, because this
    function's sessions are different objects entirely.

    Degrades ALWAYS to "no refresh this time," never to a raised exception
    that could break the read/sync it is a courtesy to: a failed proxy call
    for one tier just skips that tier (D3 degrade-never-fabricate, unaffected
    columns); an unexpected error in either DB phase is caught, logged, and
    swallowed -- the caller proceeds exactly as it would have if this
    function had never been called.
    """
    try:
        with get_background_db() as db:
            rows = db.query(MlPxqTier).filter(MlPxqTier.item_id == item_id).all()
            stale: List[_StaleTierRef] = [
                _StaleTierRef(
                    tier_id=row.id,
                    item_id=row.item_id,
                    cantidad_minima=row.cantidad_minima,
                    precio_unitario=row.precio_unitario,
                )
                for row in rows
                if _is_stale(row.costo_envio_fetched_at)
            ]
        # Session closed here (get_background_db commits -- a no-op for a
        # pure read -- and closes on exit). NO connection, from ANY
        # session, is held past this point while the fetches below run.
    except Exception:
        logger.exception("PxQ shipping refresh: failed reading stale tiers item_id=%s", item_id)
        return

    if not stale:
        return

    successes: Dict[int, float] = {}
    for ref in stale:
        try:
            amount = resolve_maybe_async(
                ml_webhook_client.get_pxq_seller_shipping_cost(
                    ref.item_id, ref.cantidad_minima, float(ref.precio_unitario)
                )
            )
        except Exception:
            # Same shape as the client's own None-on-anything collapse --
            # an exception escaping the bridge is treated identically to a
            # None return, never propagated to the caller.
            logger.exception("PxQ shipping refresh: fetch failed tier_id=%s item_id=%s", ref.tier_id, ref.item_id)
            continue
        if amount is not None:
            successes[ref.tier_id] = amount

    if not successes:
        return

    try:
        now = datetime.now(timezone.utc)
        with get_background_db() as db:
            for tier_id, amount in successes.items():
                tier = db.get(MlPxqTier, tier_id)
                if tier is None:
                    # Deleted between phase (a) and here -- nothing to
                    # stamp, and not an error worth surfacing.
                    continue
                tier.costo_envio_total = Decimal(str(amount))
                tier.costo_envio_fetched_at = now
        # Commits (once, for every row above) and closes on exit.
    except Exception:
        logger.exception("PxQ shipping refresh: failed persisting fetched shipping item_id=%s", item_id)
        return


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

    PURE DB READ -- no ML proxy call, no session held across network I/O.
    Callers that want the auto-fetch (slice B) run
    `refresh_stale_tier_shipping(item_id)` BEFORE calling this, using their
    OWN, separate sessions for that phase -- see that function's docstring.

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
