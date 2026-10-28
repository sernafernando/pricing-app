"""PARA GANAR P5 Slice B (R4) — promo opportunity vs current MLA state.

Current (X price, Y markup, Z rank) vs projected (X', Y', Z') for each
available candidate promo. Pendiente when any projection improves at least
one dimension without clearly worsening another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

import logging

from sqlalchemy.exc import SQLAlchemyError

from app.services.ml_promotions_pricing import (
    _markup_con_contexto,
    _resolve_pricing_context,
    enriquecer_markup_por_promo,
    markup_para_precio,
    precio_de_oferta,
)
from app.services.ml_promotions_service import fetch_item_promotions_bulk
from app.services.para_ganar_sugerencia import SugerenciaMla
from app.services.para_ganar_top import RankCompetitor, dense_rank_positions, our_rank_from_positions

logger = logging.getLogger(__name__)

ML_PRICED_TYPES = frozenset({"SMART", "PRE_NEGOTIATED", "PRICE_MATCHING"})
SELLER_PRICED_TYPES = frozenset({"DEAL", "SELLER_CAMPAIGN"})
PRICE_EPS = 0.01
MARKUP_EPS = 0.01
REASON_R4 = "r4"


@dataclass(frozen=True)
class MlaStateXYZ:
    price: Optional[float]
    markup: Optional[float]
    rank: Optional[int]


def clamp_deal_to_range(
    precio_sugerido: Optional[float],
    min_price: object,
    max_price: object,
) -> Optional[float]:
    if precio_sugerido is None:
        return None
    try:
        price = float(precio_sugerido)
    except (TypeError, ValueError):
        return None
    if not (price > 0):
        return None
    if min_price is not None:
        try:
            price = max(price, float(min_price))
        except (TypeError, ValueError):
            pass
    if max_price is not None:
        try:
            price = min(price, float(max_price))
        except (TypeError, ValueError):
            pass
    return price if price > 0 else None


def projected_offer_price(promo: dict[str, Any], *, precio_sugerido: Optional[float]) -> Optional[float]:
    """X' — price if we enrolled in this candidate promo."""
    ptype = str(promo.get("promotion_type") or "")
    if ptype in ML_PRICED_TYPES:
        return precio_de_oferta(promo)
    if ptype in SELLER_PRICED_TYPES:
        clamped = clamp_deal_to_range(
            precio_sugerido,
            promo.get("min_discounted_price"),
            promo.get("max_discounted_price"),
        )
        if clamped is not None:
            return clamped
        return precio_de_oferta(promo)
    return precio_de_oferta(promo)


def state_improved(current: MlaStateXYZ, projected: MlaStateXYZ) -> bool:
    """True when ≥1 of X/Y/Z is better and none is clearly worse.

    Better: lower price, higher markup, lower rank (1 is best).
    """
    better = False
    worse = False

    if current.price is not None and projected.price is not None:
        if projected.price < current.price - PRICE_EPS:
            better = True
        elif projected.price > current.price + PRICE_EPS:
            worse = True

    if current.markup is not None and projected.markup is not None:
        if projected.markup > current.markup + MARKUP_EPS:
            better = True
        elif projected.markup < current.markup - MARKUP_EPS:
            worse = True

    if current.rank is not None and projected.rank is not None:
        if projected.rank < current.rank:
            better = True
        elif projected.rank > current.rank:
            worse = True

    return better and not worse


def rank_at_price(sug: SugerenciaMla, price: float) -> Optional[int]:
    """Z' — dense rank if our listing were at `price` (full bucket peers)."""
    ranked: list[RankCompetitor] = []
    peers = sug.rank_peers or []
    if not peers:
        # Fallback: TOP board only (incomplete but better than nothing).
        for pos in sug.positions or []:
            price_ars = pos.get("price_ars")
            try:
                peer_price = float(price_ars) if price_ars is not None else None
            except (TypeError, ValueError):
                peer_price = None
            for seller in pos.get("sellers") or []:
                if not isinstance(seller, dict) or bool(seller.get("is_us")):
                    continue
                seller_id = str(seller.get("seller_id") or "").strip()
                if not seller_id or peer_price is None:
                    continue
                peers.append(
                    {
                        "seller_id": seller_id,
                        "price_ars": peer_price,
                        "is_us": False,
                        "nickname": seller.get("nickname"),
                        "item_id": seller.get("item_id"),
                        "listing_label": seller.get("listing_label"),
                    }
                )
    for peer in peers:
        if bool(peer.get("is_us")):
            continue
        seller_id = str(peer.get("seller_id") or "").strip()
        if not seller_id:
            continue
        try:
            peer_price = float(peer["price_ars"])
        except (KeyError, TypeError, ValueError):
            continue
        ranked.append(
            RankCompetitor(
                seller_id=seller_id,
                nickname=peer.get("nickname"),
                item_id=peer.get("item_id"),
                price_ars=peer_price,
                is_us=False,
                listing_label=peer.get("listing_label"),
            )
        )
    ranked.append(
        RankCompetitor(
            seller_id="us",
            nickname="Nosotros",
            item_id=sug.mla,
            price_ars=float(price),
            is_us=True,
        )
    )
    positions = dense_rank_positions(ranked)
    return our_rank_from_positions(positions)


def current_state_from_sugerencia(db: Session, sug: SugerenciaMla) -> MlaStateXYZ:
    markup = None
    if sug.our_price is not None:
        markup = markup_para_precio(db, sug.mla, float(sug.our_price))
    return MlaStateXYZ(price=sug.our_price, markup=markup, rank=sug.our_rank)


def candidate_promos(promos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for promo in promos:
        if str(promo.get("status") or "").lower() != "candidate":
            continue
        ptype = str(promo.get("promotion_type") or "")
        if ptype not in ML_PRICED_TYPES and ptype not in SELLER_PRICED_TYPES:
            continue
        out.append(promo)
    return out


def has_promo_opportunity(
    db: Session,
    sug: SugerenciaMla,
    promos: list[dict[str, Any]],
) -> bool:
    """R4: any candidate promo projects a better (X',Y',Z') than current."""
    if not sug.our_price or sug.our_rank is None:
        return False
    current = current_state_from_sugerencia(db, sug)
    candidates = candidate_promos(promos)
    if not candidates:
        return False
    # ML-priced: co-funding markup via enriquecer (context resolved once inside).
    enriquecer_markup_por_promo(db, sug.mla, candidates)
    # Seller-priced: one pricing context for all X' markups (no N+1 resolve).
    pricing_ctx = _resolve_pricing_context(db, sug.mla)
    for promo in candidates:
        x_prime = projected_offer_price(promo, precio_sugerido=sug.precio_sugerido)
        if x_prime is None:
            continue
        ptype = str(promo.get("promotion_type") or "")
        if ptype in SELLER_PRICED_TYPES and pricing_ctx is not None:
            y_f = _markup_con_contexto(db, pricing_ctx, float(x_prime), mla=sug.mla)
        else:
            y_prime = promo.get("nuestro_markup")
            try:
                y_f = float(y_prime) if y_prime is not None else None
            except (TypeError, ValueError):
                y_f = None
        z_prime = rank_at_price(sug, float(x_prime))
        projected = MlaStateXYZ(price=float(x_prime), markup=y_f, rank=z_prime)
        if state_improved(current, projected):
            return True
    return False


def load_promos_for_mlas(mla_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Fail-soft bulk promo load (empty map if mlwebhook unavailable)."""
    if not mla_ids:
        return {}
    try:
        return fetch_item_promotions_bulk(mla_ids, active_only=True)
    except RuntimeError as exc:
        logger.warning("R4: mlwebhook unavailable for promo bulk: %s", exc)
        return {mla: [] for mla in mla_ids}
    except SQLAlchemyError as exc:
        logger.warning("R4: promo bulk query failed: %s", exc)
        return {mla: [] for mla in mla_ids}
