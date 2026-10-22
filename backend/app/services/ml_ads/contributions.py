"""Brand contributions to Product Ads campaigns: the read side (ml-ads-brand-contribution S8).

Only stores what the team loads (S2). How a contribution lowers the subtracted cost (S5, S6) is the Board's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ml_ads import MlAdsCampaign, MlAdsCampaignContribution, MlAdsCampaignDay


@dataclass
class CampaignRow:
    campaign: MlAdsCampaign
    cost: Decimal
    contributions: list[MlAdsCampaignContribution] = field(default_factory=list)


def list_campaigns(db: Session, date_from: date, date_to: date) -> list[CampaignRow]:
    """Every catalogued campaign with all its contributions (by start) and its cost in `[date_from, date_to]`."""
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
