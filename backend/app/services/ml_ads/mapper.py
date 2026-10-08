"""Pure mapping of ML Product Ads responses to fact rows (ADS-3).

Facts are keyed by the advertiser that REPORTS them (the one whose listing was requested), never
by the `advertiser_id` inside the payload: a moved/revoked group appears under 714700 with
`original_advertiser_id` 25713, and each reporting advertiser closes its own day. A payload without
an identity (`id` for a group, `item_id` for an ad) cannot become a fact; that is what keeps a
per-date `aggregation_type=daily` series from ever feeding the tables (ADS-1).

Money goes through `Decimal(str(value))`: the JSON floats print as ML sent them. Only rows with
activity (cost > 0 or any non-zero base metric) are produced. Ratios (cpc, ctr, acos, roas, cvr,
sov) are derived by ML and do not count as activity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Optional

ACTIVITY_METRICS = (
    "cost",
    "clicks",
    "prints",
    "direct_amount",
    "indirect_amount",
    "direct_units_quantity",
    "indirect_units_quantity",
    "units_quantity",
    "organic_units_quantity",
    "organic_units_amount",
)


@dataclass(frozen=True)
class GroupFact:
    advertiser_id: int
    ad_group_id: int
    day: date
    campaign_id: Optional[int]
    ad_group_type: Optional[str]
    external_id: Optional[str]
    cost: Decimal
    direct_amount: Decimal
    indirect_amount: Decimal
    clicks: int
    prints: int
    units_quantity: int
    raw: Mapping[str, Any]

    @property
    def needs_drill(self) -> bool:
        """ADS-2(b): only groups that spent are drilled into their ads."""
        return self.cost > 0


@dataclass(frozen=True)
class ItemFact:
    advertiser_id: int
    ad_group_id: int
    item_id: str
    day: date
    campaign_id: Optional[int]
    cost: Decimal
    direct_amount: Decimal
    indirect_amount: Decimal
    organic_amount: Decimal
    clicks: int
    direct_units: int
    indirect_units: int
    organic_units: int
    prints: int
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class DaySummary:
    """ML's own total for the day (`metrics_summary` of `campaigns/search`)."""

    cost: Decimal
    raw: Mapping[str, Any]


def _money(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _count(value: Any) -> int:
    return int(value or 0)


def has_activity(metrics: Mapping[str, Any]) -> bool:
    return any(metrics.get(name) for name in ACTIVITY_METRICS)


def map_group(advertiser_id: int, day: date, raw: Mapping[str, Any]) -> Optional[GroupFact]:
    metrics = raw.get("metrics") or {}
    if not raw.get("id") or not has_activity(metrics):
        return None
    return GroupFact(
        advertiser_id=advertiser_id,
        ad_group_id=int(raw["id"]),
        day=day,
        campaign_id=raw.get("campaign_id"),
        ad_group_type=raw.get("ad_group_type"),
        external_id=raw.get("ad_group_external_id"),
        cost=_money(metrics.get("cost")),
        direct_amount=_money(metrics.get("direct_amount")),
        indirect_amount=_money(metrics.get("indirect_amount")),
        clicks=_count(metrics.get("clicks")),
        prints=_count(metrics.get("prints")),
        units_quantity=_count(metrics.get("units_quantity")),
        raw=raw,
    )


def map_item(advertiser_id: int, ad_group_id: int, day: date, raw: Mapping[str, Any]) -> Optional[ItemFact]:
    metrics = raw.get("metrics") or {}
    if not raw.get("item_id") or not has_activity(metrics):
        return None
    return ItemFact(
        advertiser_id=advertiser_id,
        ad_group_id=ad_group_id,
        item_id=str(raw["item_id"]),
        day=day,
        campaign_id=raw.get("campaign_id"),
        cost=_money(metrics.get("cost")),
        direct_amount=_money(metrics.get("direct_amount")),
        indirect_amount=_money(metrics.get("indirect_amount")),
        organic_amount=_money(metrics.get("organic_units_amount")),
        clicks=_count(metrics.get("clicks")),
        direct_units=_count(metrics.get("direct_units_quantity")),
        indirect_units=_count(metrics.get("indirect_units_quantity")),
        organic_units=_count(metrics.get("organic_units_quantity")),
        prints=_count(metrics.get("prints")),
        raw=raw,
    )


def map_groups_page(advertiser_id: int, day: date, body: Mapping[str, Any]) -> list[GroupFact]:
    facts = (map_group(advertiser_id, day, raw) for raw in body.get("results") or [])
    return [fact for fact in facts if fact is not None]


def map_ads_page(advertiser_id: int, ad_group_id: int, day: date, body: Mapping[str, Any]) -> list[ItemFact]:
    facts = (map_item(advertiser_id, ad_group_id, day, raw) for raw in body.get("results") or [])
    return [fact for fact in facts if fact is not None]


def parse_summary(body: Mapping[str, Any]) -> Optional[DaySummary]:
    summary = body.get("metrics_summary")
    if not isinstance(summary, Mapping) or "cost" not in summary:
        return None
    return DaySummary(cost=_money(summary["cost"]), raw=summary)
