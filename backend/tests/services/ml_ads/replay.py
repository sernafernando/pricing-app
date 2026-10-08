"""Helpers over the captured 2026-10-05 ML Ads day (see `tests/fixtures/ml_ads/README.md`)."""

from __future__ import annotations

from typing import Any

from tests.services.ml_ads.captures import load


def gauss_day() -> dict[str, Any]:
    """Advertiser 25713 on 2026-10-05, every body exactly as ML answered (full-day capture).

    `pages`: the 28 `ad_groups/search` bodies; `summary`: the `campaigns/search` body; `ads`: group id ->
    the `/ads` bodies of the 72 cost-bearing groups (82 pages). Returns fresh copies a test may mutate.
    """
    pages = load("groups_day_2026_10_05_25713.json.gz")
    ads = load("ads_day_2026_10_05_25713.json.gz")
    return {
        "pages": [p["body"] for p in pages],
        "summary": load("campaigns_summary_2026_10_05.json")["25713"]["body"],
        "ads": {int(gid): [p["body"] for p in group_pages] for gid, group_pages in ads.items()},
    }


def active_zero_cost(day: dict[str, Any]) -> list[dict[str, Any]]:
    """Real group rows of the day with activity but cost 0 (organic units): stored, never drilled."""
    activity = ("clicks", "prints", "direct_amount", "indirect_amount", "units_quantity", "organic_units_quantity")
    return [
        g
        for p in day["pages"]
        for g in p["results"]
        if g["metrics"]["cost"] == 0 and any(g["metrics"].get(k) for k in activity)
    ]
