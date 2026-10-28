"""P5 Slice B — R4 promo opportunity (X,Y,Z) vs (X',Y',Z')."""

from __future__ import annotations

from app.services.para_ganar_evaluacion_r4 import (
    MlaStateXYZ,
    clamp_deal_to_range,
    projected_offer_price,
    rank_at_price,
    state_improved,
)
from app.services.para_ganar_sugerencia import SugerenciaMla


def test_state_improved_cheaper_same_markup_and_rank() -> None:
    current = MlaStateXYZ(price=1000.0, markup=10.0, rank=2)
    projected = MlaStateXYZ(price=950.0, markup=10.0, rank=2)
    assert state_improved(current, projected) is True


def test_state_improved_better_markup_same_price() -> None:
    current = MlaStateXYZ(price=1000.0, markup=8.0, rank=2)
    projected = MlaStateXYZ(price=1000.0, markup=12.0, rank=2)
    assert state_improved(current, projected) is True


def test_state_improved_rejects_cheaper_but_worse_rank() -> None:
    current = MlaStateXYZ(price=1000.0, markup=10.0, rank=2)
    projected = MlaStateXYZ(price=900.0, markup=10.0, rank=4)
    assert state_improved(current, projected) is False


def test_projected_offer_price_seller_clamps_sugerido() -> None:
    promo = {
        "promotion_type": "DEAL",
        "min_discounted_price": 80,
        "max_discounted_price": 120,
        "price": 0,
        "suggested_discounted_price": 90,
    }
    assert projected_offer_price(promo, precio_sugerido=100.0) == 100.0
    assert projected_offer_price(promo, precio_sugerido=70.0) == 80.0


def test_projected_offer_price_smart_uses_oferta() -> None:
    promo = {
        "promotion_type": "SMART",
        "price": 880.0,
        "suggested_discounted_price": 900.0,
    }
    assert projected_offer_price(promo, precio_sugerido=1000.0) == 880.0


def test_clamp_deal_to_range_none_when_invalid() -> None:
    assert clamp_deal_to_range(None, 1, 2) is None
    assert clamp_deal_to_range(0, 1, 2) is None


def test_rank_at_price_improves_when_we_undercut() -> None:
    sug = SugerenciaMla(
        mla="MLA1",
        our_price=200.0,
        our_rank=2,
        rank_peers=[
            {"seller_id": "peer1", "price_ars": 150.0, "is_us": False},
            {"seller_id": "us", "price_ars": 200.0, "is_us": True},
            {"seller_id": "peer2", "price_ars": 250.0, "is_us": False},
        ],
    )
    assert rank_at_price(sug, 140.0) == 1
