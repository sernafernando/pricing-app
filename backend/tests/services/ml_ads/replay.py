"""Scripted ML Ads transport that replays the captured responses (see `tests/fixtures/ml_ads/README.md`).

`Replay` answers the three endpoints of the day recipe from the fixtures and records every request.
The fake clock advances one second per HTTP request.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from tests.services.ml_ads.captures import load

START = datetime(2026, 10, 8, 13, 30, tzinfo=timezone.utc)  # 10:30 in Buenos Aires

GROUPS_RE = re.compile(r"/advertisers/(\d+)/product_ads/ad_groups/search$")
SUMMARY_RE = re.compile(r"/advertisers/(\d+)/product_ads/campaigns/search$")
ADS_RE = re.compile(r"/product_ads/ad_groups/(\d+)/ads$")


class FakeClock:
    def __init__(self, start: datetime = START) -> None:
        self.start = start
        self.elapsed = 0.0

    def monotonic(self) -> float:
        return self.elapsed

    def now(self) -> datetime:
        return self.start + timedelta(seconds=self.elapsed)

    def sleep(self, seconds: float) -> None:
        self.elapsed += seconds


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


def cost_bearing(day: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """The group rows of a captured day that spent (cost > 0), by id, across every page."""
    return {g["id"]: g for p in day["pages"] for g in p["results"] if g["metrics"]["cost"] > 0}


def active_zero_cost(day: dict[str, Any]) -> list[dict[str, Any]]:
    """Real group rows of the day with activity but cost 0 (organic units): stored, never drilled."""
    activity = ("clicks", "prints", "direct_amount", "indirect_amount", "units_quantity", "organic_units_quantity")
    return [
        g
        for p in day["pages"]
        for g in p["results"]
        if g["metrics"]["cost"] == 0 and any(g["metrics"].get(k) for k in activity)
    ]


def tplink_day() -> dict[str, Any]:
    """Advertiser 714700 on 2026-10-05: the 2 real group pages (338 groups, all cost 0) and a summary with cost 0."""
    return {
        "pages": [p["body"] for p in load("groups_day_2026_10_05_714700.json.gz")],
        "summary": load("campaigns_summary_2026_10_05.json")["714700"]["body"],
        "ads": {},
    }


class Replay:
    """httpx handler for one advertiser's `{pages, summary, ads}` day; every answer is a captured body.

    A request with no captured answer fails the test loudly instead of inventing one.
    """

    def __init__(self, clock: FakeClock, day: dict[str, Any]) -> None:
        self.clock = clock
        self.day = day
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.clock.sleep(1.0)
        offset = int(request.url.params.get("offset", 0))
        if SUMMARY_RE.search(request.url.path):
            return httpx.Response(200, json=self.day["summary"])
        if GROUPS_RE.search(request.url.path):
            return httpx.Response(200, json=next(p for p in self.day["pages"] if p["paging"]["offset"] == offset))
        if match := ADS_RE.search(request.url.path):
            pages = self.day["ads"][int(match.group(1))]
            return httpx.Response(200, json=next(p for p in pages if p["paging"]["offset"] == offset))
        raise AssertionError(f"unexpected request {request.url}")

    # --- inspection -----------------------------------------------------------------------

    def calls(self, pattern: re.Pattern[str]) -> list[httpx.Request]:
        return [r for r in self.requests if pattern.search(r.url.path)]

    def group_pages(self) -> list[int]:
        return [int(r.url.params["offset"]) for r in self.calls(GROUPS_RE)]

    def ads_calls(self) -> list[tuple[int, int]]:
        """`(ad_group_id, offset)` of every `/ads` request, in order."""
        return [(int(ADS_RE.search(r.url.path).group(1)), int(r.url.params["offset"])) for r in self.calls(ADS_RE)]


def make_client(replay: Replay, monkeypatch, *, token: Optional[dict] = None) -> MlHttpClient:
    monkeypatch.setattr(settings, "ML_USER_ID", "413658225")
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "7211863044554429")
    loaded = {"access_token": "tok-secret", "expires_epoch": 9e12} if token is None else token
    return MlHttpClient(
        pacer=Pacer(clock=replay.clock, rate_per_sec=1000.0),
        transport=httpx.MockTransport(replay),
        token_loader=lambda: loaded or None,
        now=replay.clock.now,
    )
