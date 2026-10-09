"""Request builders for the ML Ads API (ADS-1, ADS-2, D5).

Pure functions: each returns the family (counter bucket), path, params and per-call headers for
`MlHttpClient.get`. Every per-group and per-ad request is a ONE-DAY window (`date_from == date_to`)
and never carries `aggregation_type=daily`, which collapses identity (#2276). Ids that end up
inside a path are coerced to `int`, so nothing but digits can be interpolated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

PRODUCT_ADS_API_VERSION = "2"
ADVERTISERS_API_VERSION = "1"
DISPLAY_API_VERSION = "1"

GROUPS_PAGE_SIZE = 200
ADS_PAGE_SIZE = 50

METRICS = ",".join(
    (
        "clicks",
        "prints",
        "ctr",
        "cpc",
        "cost",
        "acos",
        "roas",
        "cvr",
        "sov",
        "direct_units_quantity",
        "indirect_units_quantity",
        "units_quantity",
        "direct_amount",
        "indirect_amount",
        "total_amount",
        "organic_units_quantity",
        "organic_units_amount",
    )
)


@dataclass(frozen=True)
class AdsRequest:
    family: str
    path: str
    params: Mapping[str, Any]
    headers: Mapping[str, str]


def _int_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError(f"expected an integer id, got {type(value).__name__}")
    text = str(value)
    if not text.isdigit():
        raise ValueError(f"expected an integer id, got {text!r}")
    return int(text)


def _one_day(day: date) -> dict[str, str]:
    return {"date_from": day.isoformat(), "date_to": day.isoformat()}


def _offset(value: int) -> int:
    if value < 0:
        raise ValueError("offset must not be negative")
    return value


def _product_ads_headers() -> dict[str, str]:
    return {"Api-Version": PRODUCT_ADS_API_VERSION}


def advertisers_request(product_id: str) -> AdsRequest:
    return AdsRequest(
        family="ads_advertisers",
        path="/advertising/advertisers",
        params={"product_id": product_id},
        headers={"Api-Version": ADVERTISERS_API_VERSION},
    )


def campaigns_summary_request(advertiser_id: Any, day: date) -> AdsRequest:
    """`campaigns/search` for the day with `metrics_summary`: ML's own total, the ledger's closing figure."""
    return AdsRequest(
        family="ads_campaigns",
        path=f"/advertising/MLA/advertisers/{_int_id(advertiser_id)}/product_ads/campaigns/search",
        params={**_one_day(day), "metrics": METRICS, "metrics_summary": "true"},
        headers=_product_ads_headers(),
    )


def ad_groups_request(advertiser_id: Any, day: date, *, offset: int) -> AdsRequest:
    return AdsRequest(
        family="ads_groups",
        path=f"/advertising/MLA/advertisers/{_int_id(advertiser_id)}/product_ads/ad_groups/search",
        params={**_one_day(day), "metrics": METRICS, "limit": GROUPS_PAGE_SIZE, "offset": _offset(offset)},
        headers=_product_ads_headers(),
    )


def group_ads_request(ad_group_id: Any, day: date, *, offset: int) -> AdsRequest:
    return AdsRequest(
        family="ads_group_ads",
        path=f"/advertising/MLA/product_ads/ad_groups/{_int_id(ad_group_id)}/ads",
        params={**_one_day(day), "metrics": METRICS, "limit": ADS_PAGE_SIZE, "offset": _offset(offset)},
        headers=_product_ads_headers(),
    )


def display_campaigns_request(advertiser_id: Any, day: date) -> AdsRequest:
    """The Display campaigns of an advertiser (account-level, Api-Version 1). The capture sent one-day dates."""
    return AdsRequest(
        family="ads_display",
        path=f"/advertising/advertisers/{_int_id(advertiser_id)}/display/campaigns",
        params=_one_day(day),
        headers={"Api-Version": DISPLAY_API_VERSION},
    )


def display_metrics_request(advertiser_id: Any, campaign_id: Any, day: date) -> AdsRequest:
    return AdsRequest(
        family="ads_display",
        path=f"/advertising/advertisers/{_int_id(advertiser_id)}/display/campaigns/{_int_id(campaign_id)}/metrics",
        params=_one_day(day),
        headers={"Api-Version": DISPLAY_API_VERSION},
    )
