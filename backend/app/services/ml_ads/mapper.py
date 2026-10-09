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


def parse_advertisers(body: Mapping[str, Any]) -> list[int]:
    """Advertiser ids of `GET /advertising/advertisers`; an entry without a numeric id is ignored."""
    ids = (entry.get("advertiser_id") for entry in body.get("advertisers") or [] if isinstance(entry, Mapping))
    return sorted({int(i) for i in ids if isinstance(i, int) and not isinstance(i, bool)})


# --- Display (account-level, ADS-9) -----------------------------------------------------------------

DISPLAY_ACTIVITY_METRICS = ("consumed_budget", "prints", "clicks", "reach", "active_views", "completed_views")


@dataclass(frozen=True)
class DisplayFact:
    """One Display campaign on one day. `consumed_budget` is stored as ML returns it (net of IVA, owner Q10)."""

    advertiser_id: int
    campaign_id: int
    day: date
    consumed_budget: Decimal
    prints: int
    clicks: int
    reach: int
    raw: Mapping[str, Any]


def parse_display_campaigns(body: Mapping[str, Any]) -> list[int]:
    """Campaign ids of `display/campaigns`, in id order (stable between runs); an entry without a numeric id is ignored."""
    ids = (entry.get("id") for entry in body.get("results") or [] if isinstance(entry, Mapping))
    return sorted({i for i in ids if isinstance(i, int) and not isinstance(i, bool)})


def map_display_metrics(advertiser_id: int, campaign_id: int, day: date, body: Mapping[str, Any]) -> list[DisplayFact]:
    """The campaign's row for `day`. A row dated otherwise is not this day's fact; no activity, no row."""
    facts = []
    for entry in body.get("metrics") or []:
        if not isinstance(entry, Mapping) or entry.get("date") != day.isoformat():
            continue
        if not any(entry.get(name) for name in DISPLAY_ACTIVITY_METRICS):
            continue
        facts.append(
            DisplayFact(
                advertiser_id=advertiser_id,
                campaign_id=campaign_id,
                day=day,
                consumed_budget=_money(entry.get("consumed_budget")),
                prints=_count(entry.get("prints")),
                clicks=_count(entry.get("clicks")),
                reach=_count(entry.get("reach")),
                raw=entry,
            )
        )
    return facts


# --- Brand Ads (account-level, informational, ADS-10) ------------------------------------------------


@dataclass(frozen=True)
class BrandFact:
    """One advertiser's Brand Ads figures on one day. `cost` is `dashboard.consumed_budget`; it is never subtracted."""

    advertiser_id: int
    day: date
    cost: Decimal
    prints: int
    clicks: int
    raw: Mapping[str, Any]


def _dashboard_point(body: Mapping[str, Any], metric: str, day: date) -> Any:
    """The `y` of the `{x, y}` point of `day` in `dashboard.<metric>`; None when the series has no point for it."""
    dashboard = body.get("dashboard")
    series = dashboard.get(metric) if isinstance(dashboard, Mapping) else None
    for point in series if isinstance(series, list) else []:
        if isinstance(point, Mapping) and point.get("x") == day.isoformat():
            return point.get("y")
    return None


def map_brand_day(advertiser_id: int, day: date, body: Mapping[str, Any]) -> Optional[BrandFact]:
    """The day's fact, or None when it is all zero (no activity, no row; the ledger still closes)."""
    cost = _money(_dashboard_point(body, "consumed_budget", day))
    prints = _count(_dashboard_point(body, "prints", day))
    clicks = _count(_dashboard_point(body, "clicks", day))
    if not (cost or prints or clicks):
        return None
    return BrandFact(advertiser_id=advertiser_id, day=day, cost=cost, prints=prints, clicks=clicks, raw=body)


def parse_brand_summary(body: Mapping[str, Any]) -> Optional[DaySummary]:
    """ML's own total for the one-day window (`summary.consumed_budget`); None when the answer has none."""
    summary = body.get("summary")
    if not isinstance(summary, Mapping) or summary.get("consumed_budget") is None:
        return None
    return DaySummary(cost=_money(summary["consumed_budget"]), raw=summary)
