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


@dataclass(frozen=True)
class RankPositionSeller:
    seller_id: str
    nickname: Optional[str]
    item_id: Optional[str]
    is_us: bool


@dataclass(frozen=True)
class RankPosition:
    rank: int
    price_ars: float
    seller_count: int
    sellers: tuple[RankPositionSeller, ...]


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
                    }
                    for s in p.sellers
                ],
            }
            for p in top
        ],
        "suggestion_status": "none",
    }
