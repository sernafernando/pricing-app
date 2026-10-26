"""Brand contributions to Product Ads campaigns: reads and writes (ml-ads-brand-contribution S4, S7, S8).

Only stores what the team loads (S2). How a contribution lowers the subtracted cost (S5, S6) is the Board's job; the
loading page's figures (`contribution_in`, `preview`, ml-ads-contribution-redesign S6) repeat the Board's rule over the
same item rows so both show the same amount.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session

from app.models.ml_ads import MlAdsCampaign, MlAdsCampaignContribution, MlAdsCampaignDay, MlAdsItemDay

logger = logging.getLogger(__name__)

# ponytail: advertiser names hardcoded (not stored); persist them from the Ads API when the catalogue sync gains them.
# These are the two advertisers the Ads API lists for the account; any other shows its id.
ADVERTISER_NAMES = {25713: "GAUSS", 714700: "TPLINK"}


class ContributionError(Exception):
    """A rule the API reports as 422 on `field`."""

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name


@dataclass(frozen=True)
class ContributionData:
    advertiser_id: int
    campaign_id: int
    kind: str
    value: Decimal
    date_from: date
    date_to: date
    brand: Optional[str]
    note: Optional[str]
    settlement: Optional[str] = None


@dataclass
class CampaignRow:
    campaign: MlAdsCampaign
    cost: Decimal
    contributions: list[MlAdsCampaignContribution] = field(default_factory=list)
    contribution: Decimal = Decimal(0)  # what the contributions cover of the range's cost


@dataclass(frozen=True)
class Preview:
    spend: Decimal  # the campaign's item-row cost over the contribution's range
    counted: Decimal  # what the Board subtracts of it


def list_campaigns(db: Session, date_from: date, date_to: date) -> list[CampaignRow]:
    """Every catalogued campaign with all its contributions (by start) and its cost in `[date_from, date_to]`.

    All contributions, not only those touching the range: the loading screen lists them all. The catalogue is only
    ever upserted (nothing deletes from `ml_ads_campaigns`) and writes require a catalogued campaign, so no
    contribution is left without its campaign. Not paginated, like the other `/ml-ads` reads: two advertisers."""
    day = MlAdsCampaignDay
    sums = (
        db.query(day.advertiser_id, day.campaign_id, func.sum(day.cost))
        .filter(day.day.between(date_from, date_to))
        .group_by(day.advertiser_id, day.campaign_id)
    )
    costs = {(advertiser, campaign): total for advertiser, campaign, total in sums}
    rows = {
        (c.advertiser_id, c.campaign_id): CampaignRow(c, Decimal(costs.get((c.advertiser_id, c.campaign_id)) or 0))
        for c in db.query(MlAdsCampaign).order_by(MlAdsCampaign.advertiser_id, MlAdsCampaign.campaign_id)
    }
    contributions = (
        db.query(MlAdsCampaignContribution)
        .order_by(MlAdsCampaignContribution.date_from, MlAdsCampaignContribution.id)
        .all()
    )
    daily = _daily_spend(db, contributions)
    for contribution in contributions:
        row = rows.get((contribution.advertiser_id, contribution.campaign_id))
        if row is not None:
            row.contributions.append(contribution)
            row.contribution += contribution_in(daily, contribution, date_from, date_to)
    return list(rows.values())


DailySpend = dict[tuple[int, int], dict[date, Decimal]]


def _daily_spend(db: Session, contributions: list[MlAdsCampaignContribution]) -> DailySpend:
    """In one query, the item-row cost per (advertiser, campaign) and day of every campaign with a contribution,
    over the span its contributions cover."""
    if not contributions:
        return {}
    item = MlAdsItemDay
    keys = {(c.advertiser_id, c.campaign_id) for c in contributions}
    rows = (
        db.query(item.advertiser_id, item.campaign_id, item.day, func.sum(item.cost))
        .filter(
            tuple_(item.advertiser_id, item.campaign_id).in_(keys),
            item.day.between(min(c.date_from for c in contributions), max(c.date_to for c in contributions)),
        )
        .group_by(item.advertiser_id, item.campaign_id, item.day)
    )
    daily: DailySpend = {}
    for advertiser, campaign, day, total in rows:
        daily.setdefault((advertiser, campaign), {})[day] = Decimal(total or 0)
    return daily


def _sum_spend(daily: DailySpend, row: MlAdsCampaignContribution, start: date, end: date) -> Decimal:
    days = daily.get((row.advertiser_id, row.campaign_id), {})
    return sum((cost for day, cost in days.items() if start <= day <= end), Decimal(0))


def _spend(db: Session, advertiser_id: int, campaign_id: int, start: date, end: date) -> Decimal:
    """The campaign's Product Ads cost over `[start, end]` on the Board's basis: its item rows."""
    item = MlAdsItemDay
    total = (
        db.query(func.sum(item.cost))
        .filter(item.advertiser_id == advertiser_id, item.campaign_id == campaign_id, item.day.between(start, end))
        .scalar()
    )
    return Decimal(total or 0)


def _counted(kind: str, value: Decimal, settlement: Optional[str], spend: Decimal) -> Decimal:
    """What a contribution covers of a range that spent `spend` (S5, S6): p% of it, or the fixed amount (`full`: all of
    it; `refund_difference`: at most `spend`). A fixed amount needs spend to spread over, as on the Board."""
    if kind == "percentage":
        return spend * value / 100
    if spend <= 0:
        return Decimal(0)
    return value if settlement == "full" else min(value, spend)


def contribution_in(daily: DailySpend, row: MlAdsCampaignContribution, date_from: date, date_to: date) -> Decimal:
    """The part of `row` that falls on `[date_from, date_to]`: a fixed amount reaches the window by the window's share
    of the WHOLE range's spend, like the Board's per-row spread. `daily` comes from `_daily_spend`."""
    start, end = max(row.date_from, date_from), min(row.date_to, date_to)
    if start > end:
        return Decimal(0)
    window = _sum_spend(daily, row, start, end)
    if row.kind == "percentage":
        return _counted(row.kind, Decimal(row.value), None, window)
    spend = _sum_spend(daily, row, row.date_from, row.date_to)
    if spend <= 0:
        return Decimal(0)
    return _counted(row.kind, Decimal(row.value), row.settlement, spend) * window / spend


def preview(db: Session, data: ContributionData) -> Preview:
    """What `data` would cover if saved, over its whole range. Writes nothing."""
    spend = _spend(db, data.advertiser_id, data.campaign_id, data.date_from, data.date_to)
    return Preview(spend, _counted(data.kind, data.value, data.settlement, spend))


def _check(db: Session, data: ContributionData, exclude_id: Optional[int] = None) -> None:
    """The campaign is catalogued (its row is locked so two writes on one campaign serialize) and no other
    contribution of it shares a day with `[date_from, date_to]` (both ends inclusive)."""
    campaign = (
        db.query(MlAdsCampaign)
        .filter(MlAdsCampaign.advertiser_id == data.advertiser_id, MlAdsCampaign.campaign_id == data.campaign_id)
        .with_for_update()
        .first()
    )
    if campaign is None:
        raise ContributionError(
            "campaign_id", f"campaign {data.campaign_id} of advertiser {data.advertiser_id} is unknown"
        )
    clash = db.query(MlAdsCampaignContribution.id).filter(
        MlAdsCampaignContribution.advertiser_id == data.advertiser_id,
        MlAdsCampaignContribution.campaign_id == data.campaign_id,
        MlAdsCampaignContribution.date_from <= data.date_to,
        MlAdsCampaignContribution.date_to >= data.date_from,
    )
    if exclude_id is not None:
        clash = clash.filter(MlAdsCampaignContribution.id != exclude_id)
    if clash.first() is not None:
        raise ContributionError("date_from", "the range overlaps another contribution of the same campaign")


def _locked(db: Session, contribution_id: int) -> Optional[MlAdsCampaignContribution]:
    """The contribution row under FOR UPDATE, taken before the campaign lock so edit and delete serialize."""
    return (
        db.query(MlAdsCampaignContribution)
        .filter(MlAdsCampaignContribution.id == contribution_id)
        .with_for_update()
        .one_or_none()
    )


def _apply(row: MlAdsCampaignContribution, data: ContributionData, user_id: int) -> None:
    for name, value in vars(data).items():
        setattr(row, name, value)
    row.updated_by_id = user_id


def create(db: Session, data: ContributionData, user_id: int) -> MlAdsCampaignContribution:
    _check(db, data)
    row = MlAdsCampaignContribution(created_by_id=user_id)
    _apply(row, data, user_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update(
    db: Session, contribution_id: int, data: ContributionData, user_id: int
) -> Optional[MlAdsCampaignContribution]:
    """`None` when the contribution does not exist (also when a concurrent delete wins the row lock)."""
    row = _locked(db, contribution_id)
    if row is None:
        return None
    if (row.advertiser_id, row.campaign_id) != (data.advertiser_id, data.campaign_id):
        raise ContributionError(
            "campaign_id", "a contribution cannot move to another campaign; delete it and load it again"
        )
    _check(db, data, exclude_id=contribution_id)
    _apply(row, data, user_id)
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, contribution_id: int, user_id: int) -> bool:
    """The row goes away; the log line keeps who removed what (the table only knows creator and last editor)."""
    row = _locked(db, contribution_id)
    if row is None:
        return False
    logger.info(
        "ml-ads contribution %s deleted by user %s: advertiser %s campaign %s %s %s %s..%s",
        row.id,
        user_id,
        row.advertiser_id,
        row.campaign_id,
        row.kind,
        row.value,
        row.date_from,
        row.date_to,
    )
    db.delete(row)
    db.commit()
    return True
