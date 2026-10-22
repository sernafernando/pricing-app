"""Brand contributions to Product Ads campaigns: reads and writes (ml-ads-brand-contribution S4, S7, S8).

Only stores what the team loads (S2). How a contribution lowers the subtracted cost (S5, S6) is the Board's job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ml_ads import MlAdsCampaign, MlAdsCampaignContribution, MlAdsCampaignDay

logger = logging.getLogger(__name__)


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


@dataclass
class CampaignRow:
    campaign: MlAdsCampaign
    cost: Decimal
    contributions: list[MlAdsCampaignContribution] = field(default_factory=list)


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
    contributions = db.query(MlAdsCampaignContribution).order_by(
        MlAdsCampaignContribution.date_from, MlAdsCampaignContribution.id
    )
    for contribution in contributions:
        row = rows.get((contribution.advertiser_id, contribution.campaign_id))
        if row is not None:
            row.contributions.append(contribution)
    return list(rows.values())


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
    """`None` when the contribution does not exist."""
    row = db.get(MlAdsCampaignContribution, contribution_id)
    if row is None:
        return None
    _check(db, data, exclude_id=contribution_id)
    _apply(row, data, user_id)
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, contribution_id: int, user_id: int) -> bool:
    """The row goes away; the log line keeps who removed what (the table only knows creator and last editor)."""
    row = db.get(MlAdsCampaignContribution, contribution_id)
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
