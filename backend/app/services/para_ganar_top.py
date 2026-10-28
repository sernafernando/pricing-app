"""PARA GANAR TOP ranking — dense rank by price (D12).

Pure helpers: no DB. Ties at the same price_ars share a rank; the next
distinct price is rank+1. TOP N means ranks <= N, not a row LIMIT.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class RankCompetitor:
    seller_id: str
    nickname: Optional[str]
    item_id: Optional[str]
    price_ars: float
    is_us: bool = False
    listing_label: Optional[str] = None
    markup: Optional[float] = None


@dataclass(frozen=True)
class SuggestedPriceResult:
    """PARA GANAR suggested price vs peers in the same bucket (Pro-style)."""

    precio_sugerido: float
    delta_ars: float
    suggestion_status: str  # winning | losing
    referent_seller_id: Optional[str]
    referent_nickname: Optional[str]
    referent_reason: str  # cheapest | markup_min


def compute_suggested_price(
    ranked: list[RankCompetitor],
    *,
    markup_min: Optional[float] = None,
    precio_min: Optional[float] = None,
    precio_max: Optional[float] = None,
) -> Optional[SuggestedPriceResult]:
    """Referent = cheapest peer (optional markup floor); delta as in Pro.

    - Losing (our > referent): delta = sugerido − our (negative ⇒ bajar).
    - Winning (our ≤ referent): delta = next peer above us − our (holgura a subir);
      0 if we are alone at the bottom of the peer ladder.
    """
    us = next((c for c in ranked if c.is_us), None)
    peers = sorted(
        (c for c in ranked if not c.is_us),
        key=lambda c: (c.price_ars, (c.nickname or "").lower(), c.seller_id),
    )
    if us is None or not peers:
        return None

    referent = peers[0]
    reason = "cheapest"
    if markup_min is not None:
        floored = [c for c in peers if c.markup is not None and c.markup >= markup_min]
        if floored:
            referent = floored[0]
            reason = "markup_min"

    sugerido = float(referent.price_ars)
    if precio_min is not None:
        sugerido = max(sugerido, float(precio_min))
    if precio_max is not None:
        sugerido = min(sugerido, float(precio_max))

    if us.price_ars <= referent.price_ars:
        above = [c for c in peers if c.price_ars > us.price_ars]
        delta = (above[0].price_ars - us.price_ars) if above else 0.0
        status = "winning"
    else:
        delta = sugerido - us.price_ars
        status = "losing"

    return SuggestedPriceResult(
        precio_sugerido=sugerido,
        delta_ars=float(delta),
        suggestion_status=status,
        referent_seller_id=referent.seller_id,
        referent_nickname=referent.nickname,
        referent_reason=reason,
    )


def peer_referent_notes(
    ranked: list[RankCompetitor],
    *,
    markup_min: Optional[float] = None,
    precio_min: Optional[float] = None,
    precio_max: Optional[float] = None,
    referent_seller_id: Optional[str] = None,
) -> dict[str, str]:
    """Short TOP-board labels: who is the referent vs discarded by criteria.

    Excluded sellers never reach `ranked` (filtered earlier). Notes are only for
    peers that appear on the board.
    """
    notes: dict[str, str] = {}
    for competitor in ranked:
        if competitor.is_us:
            continue
        if referent_seller_id and competitor.seller_id == referent_seller_id:
            notes[competitor.seller_id] = "Referente"
            continue
        if markup_min is not None:
            if competitor.markup is None:
                notes[competitor.seller_id] = "Sin markup"
                continue
            if competitor.markup < float(markup_min):
                notes[competitor.seller_id] = "Descartado: markup mín."
                continue
        if precio_min is not None and competitor.price_ars < float(precio_min):
            notes[competitor.seller_id] = "Descartado: precio mín."
            continue
        if precio_max is not None and competitor.price_ars > float(precio_max):
            notes[competitor.seller_id] = "Descartado: precio máx."
            continue
    return notes


@dataclass(frozen=True)
class RankPositionSeller:
    seller_id: str
    nickname: Optional[str]
    item_id: Optional[str]
    is_us: bool
    listing_label: Optional[str] = None
    referent_note: Optional[str] = None


@dataclass(frozen=True)
class RankPosition:
    rank: int
    price_ars: float
    seller_count: int
    sellers: tuple[RankPositionSeller, ...]


def bucket_display_label(
    bucket_key: Optional[str],
    *,
    listing_label: Optional[str] = None,
) -> Optional[str]:
    """Human label for the TOP board (API listing_label, else key → Premium · N cuotas)."""
    if listing_label:
        text = str(listing_label).strip()
        if text:
            return text[:64]
    if not bucket_key or not isinstance(bucket_key, str):
        return None
    parts = bucket_key.split("|", 1)
    if len(parts) != 2:
        return None
    listing, cuotas = parts[0].strip().lower(), parts[1].strip()
    if cuotas.endswith("c") and cuotas[:-1].isdigit():
        return f"Premium · {cuotas[:-1]} cuotas"
    if cuotas.isdigit() and cuotas != "0":
        return f"Premium · {cuotas} cuotas"
    if listing == "gold_special" or cuotas in ("0", ""):
        return "Clásica"
    return None


def dense_rank_positions(competitors: list[RankCompetitor]) -> list[RankPosition]:
    """Sort by price ascending; equal prices share dense rank (D12)."""
    if not competitors:
        return []

    ordered = sorted(
        competitors,
        key=lambda c: (c.price_ars, 0 if c.is_us else 1, (c.nickname or "").lower(), c.seller_id),
    )

    positions: list[RankPosition] = []
    current_rank = 0
    last_price: Optional[float] = None
    bucket: list[RankCompetitor] = []

    def flush() -> None:
        nonlocal bucket
        if not bucket:
            return
        sellers = tuple(
            RankPositionSeller(
                seller_id=c.seller_id,
                nickname=c.nickname,
                item_id=c.item_id,
                is_us=c.is_us,
                listing_label=c.listing_label,
            )
            for c in bucket
        )
        positions.append(
            RankPosition(
                rank=current_rank,
                price_ars=bucket[0].price_ars,
                seller_count=len(sellers),
                sellers=sellers,
            )
        )
        bucket = []

    for competitor in ordered:
        if last_price is None or competitor.price_ars != last_price:
            flush()
            current_rank += 1
            last_price = competitor.price_ars
        bucket.append(competitor)
    flush()
    return positions


def our_rank_from_positions(positions: list[RankPosition]) -> Optional[int]:
    for position in positions:
        if any(s.is_us for s in position.sellers):
            return position.rank
    return None


def positions_within_top(positions: list[RankPosition], top_n: int) -> list[RankPosition]:
    if top_n < 1:
        return []
    return [p for p in positions if p.rank <= top_n]


def board_to_dict(
    *,
    positions: list[RankPosition],
    top_n: int,
    our_price: Optional[float],
    our_rank: Optional[int],
    excluded_count: int,
    catalog_product_id: Optional[str],
    snapshot_at: Optional[str],
    bucket_label: Optional[str] = None,
) -> dict[str, Any]:
    top = positions_within_top(positions, top_n)
    in_top = our_rank is not None and our_rank <= top_n
    return {
        "catalog_product_id": catalog_product_id,
        "snapshot_at": snapshot_at,
        "our_price": our_price,
        "our_rank": our_rank,
        "top_sellers": top_n,
        "in_top": in_top,
        "excluded_count": excluded_count,
        "bucket_label": bucket_label,
        "positions": [
            {
                "rank": p.rank,
                "price_ars": p.price_ars,
                "seller_count": p.seller_count,
                "sellers": [
                    {
                        "seller_id": s.seller_id,
                        "nickname": s.nickname,
                        "item_id": s.item_id,
                        "is_us": s.is_us,
                        "listing_label": s.listing_label,
                        "referent_note": s.referent_note,
                    }
                    for s in p.sellers
                ],
            }
            for p in top
        ],
        "suggestion_status": "none",
    }
