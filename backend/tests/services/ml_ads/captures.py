"""Loaders for the captured ML Ads responses under `tests/fixtures/ml_ads/` (sources in its README)."""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_ads"


@lru_cache(maxsize=None)
def _read(name: str) -> str:
    path = FIXTURES / name
    if name.endswith(".gz"):
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    return path.read_text(encoding="utf-8")


def load(name: str) -> Any:
    """A fresh copy of a fixture (`.json` or `.json.gz`), safe for a test to mutate."""
    return json.loads(_read(name))


def group_row(ad_group_id: int) -> dict:
    """The real 2026-10-05 `ad_groups/search` row of an advertiser 25713 group."""
    for page in load("groups_day_2026_10_05_25713.json.gz"):
        for group in page["body"]["results"]:
            if group["id"] == ad_group_id:
                return group
    raise KeyError(ad_group_id)


def group_ads(ad_group_id: int) -> list[dict]:
    """Every real ad row of a drilled 25713 group, across its `/ads` pages."""
    pages = load("ads_day_2026_10_05_25713.json.gz")[str(ad_group_id)]
    return [ad for page in pages for ad in page["body"]["results"]]
