"""The MCP port of the Sugerida pick (L9) runs the same cases as the frontend's pickPonerPreciosPromos.js."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.mcp import promo_pick

SHARED = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "pick_mejores_candidatas_cases.json").read_text()
)
NOW = datetime.fromisoformat(SHARED["now"].replace("Z", "+00:00"))


@pytest.mark.parametrize("case", SHARED["pick_cases"], ids=lambda c: c["name"])
def test_pick_mejores_candidatas_matches_the_frontend(case):
    baseline = case["baseline"]
    picked = promo_pick.pick_mejores_candidatas(
        case["promotions"],
        baseline_price=baseline["price"],
        baseline_markup=baseline["markup"],
        baseline_sell_in_out=baseline["sell_in_out"],
        now=NOW,
    )
    assert {t: p["promotion_id"] for t, p in picked.items() if p} == case["expected"]
    assert set(picked) == set(promo_pick.CHOOSER_SLOT_TYPES)


@pytest.mark.parametrize("case", SHARED["baseline_cases"], ids=lambda c: c["name"])
def test_baseline_promo_matches_the_frontend(case):
    promo = promo_pick.baseline_promo(case["promotions"])
    assert (promo or {}).get("promotion_id") == case["expected"]


def _slot(pid: str, price: float, markup: float, sell_in_out: float | None) -> dict:
    return {"promotion_id": pid, "price": price, "nuestro_markup": markup, "markup_sell_in_out": sell_in_out}


def test_best_is_the_suggestion_with_the_highest_markup_with_sell_in():
    slots = {"SMART": _slot("A", 900, 30, 20), "DEAL": _slot("B", 950, 10, 25), "LIGHTNING": None}
    assert promo_pick.best_suggestion(slots)["promotion_id"] == "B"


def test_best_falls_back_to_plain_markup_and_breaks_ties_by_lower_price():
    assert (
        promo_pick.best_suggestion({"SMART": _slot("A", 900, 30, None), "DEAL": _slot("B", 950, 10, 25)})[
            "promotion_id"
        ]
        == "A"
    )
    assert (
        promo_pick.best_suggestion({"SMART": _slot("A", 950, 20, 20), "DEAL": _slot("B", 900, 20, 20)})["promotion_id"]
        == "B"
    )
    assert promo_pick.best_suggestion({"SMART": None}) is None


def test_improvement_in_points_and_percent_on_the_same_basis():
    current = {"nuestro_markup": 10.0, "markup_sell_in_out": 12.0}
    assert promo_pick.improvement(_slot("A", 900, 15, 18), current) == {
        "points": 6.0,
        "percent": 50.0,
        "basis": "markup_sell_in_out",
    }
    assert promo_pick.improvement(_slot("A", 900, 15, None), current) == {
        "points": 5.0,
        "percent": 50.0,
        "basis": "nuestro_markup",
    }
    assert promo_pick.improvement(None, current) is None
    assert promo_pick.improvement(_slot("A", 900, 5, None), {"nuestro_markup": 0.0})["percent"] is None
