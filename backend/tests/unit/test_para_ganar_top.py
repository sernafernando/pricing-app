"""Pure D12 dense-rank helper for PARA GANAR TOP."""

from __future__ import annotations

from app.services.para_ganar_top import (
    RankCompetitor,
    bucket_display_label,
    compute_suggested_price,
    dense_rank_positions,
    our_rank_from_positions,
    positions_within_top,
)


def test_dense_rank_ties_share_position_d12_example() -> None:
    # Two at #1 + three at #2 = top 2 positions, five sellers.
    competitors = [
        RankCompetitor("a", "A", "MLA1", 100.0),
        RankCompetitor("b", "B", "MLA2", 100.0),
        RankCompetitor("c", "C", "MLA3", 105.0),
        RankCompetitor("d", "D", "MLA4", 105.0),
        RankCompetitor("e", "E", "MLA5", 105.0),
        RankCompetitor("us", "US", "MLAUS", 108.0, is_us=True),
    ]
    positions = dense_rank_positions(competitors)
    assert [p.rank for p in positions] == [1, 2, 3]
    assert positions[0].seller_count == 2
    assert positions[1].seller_count == 3
    assert positions[2].seller_count == 1
    assert positions[2].sellers[0].is_us is True

    top2 = positions_within_top(positions, 2)
    assert [p.rank for p in top2] == [1, 2]
    assert sum(p.seller_count for p in top2) == 5
    assert our_rank_from_positions(positions) == 3


def test_empty_competitors() -> None:
    assert dense_rank_positions([]) == []
    assert our_rank_from_positions([]) is None


def test_bucket_display_label() -> None:
    assert bucket_display_label("gold_pro|3", listing_label="Premium · 3 cuotas") == "Premium · 3 cuotas"
    assert bucket_display_label("gold_pro|6") == "Premium · 6 cuotas"
    assert bucket_display_label("gold_special|0") == "Clásica"
    assert bucket_display_label(None) is None


def test_suggested_price_losing_vs_cheapest() -> None:
    ranked = [
        RankCompetitor("a", "A", "MLA1", 100.0, markup=10.0),
        RankCompetitor("b", "B", "MLA2", 110.0, markup=12.0),
        RankCompetitor("us", "US", "MLAUS", 120.0, is_us=True),
    ]
    result = compute_suggested_price(ranked, markup_min=5.0)
    assert result is not None
    assert result.suggestion_status == "losing"
    assert result.precio_sugerido == 100.0
    assert result.delta_ars == -20.0
    assert result.referent_reason == "markup_min"
    assert result.referent_nickname == "A"


def test_suggested_price_skips_low_markup_peer() -> None:
    ranked = [
        RankCompetitor("cheap", "CHEAP", "MLA1", 90.0, markup=1.0),
        RankCompetitor("ok", "OK", "MLA2", 100.0, markup=8.0),
        RankCompetitor("us", "US", "MLAUS", 120.0, is_us=True),
    ]
    result = compute_suggested_price(ranked, markup_min=5.0)
    assert result is not None
    assert result.precio_sugerido == 100.0
    assert result.referent_nickname == "OK"
    assert result.referent_reason == "markup_min"


def test_suggested_price_winning_air_to_second() -> None:
    ranked = [
        RankCompetitor("us", "US", "MLAUS", 100.0, is_us=True),
        RankCompetitor("b", "B", "MLA2", 100.0, markup=10.0),
        RankCompetitor("c", "C", "MLA3", 115.0, markup=12.0),
    ]
    result = compute_suggested_price(ranked)
    assert result is not None
    assert result.suggestion_status == "winning"
    assert result.precio_sugerido == 100.0
    assert result.delta_ars == 15.0


def test_suggested_price_alone_returns_none() -> None:
    ranked = [RankCompetitor("us", "US", "MLAUS", 100.0, is_us=True)]
    assert compute_suggested_price(ranked) is None
