"""ml_ads_campaigns + ml_ads_campaign_days (ml-ads-campaigns)

Revision ID: 20261029_ml_ads_campaigns
Revises: 20261028_tplink_solo_permiso
Create Date: 2026-10-16

The Product Ads campaigns that the day's `campaigns/search` call returns: the latest catalog per campaign
and its metrics per day. No cached sums (ADS-4). Downgrade drops exactly these two tables.

down_revision must be the single alembic head of origin/main at merge; re-chain it if main advanced.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261029_ml_ads_campaigns"
down_revision: Union[str, None] = "20261028_tplink_solo_permiso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _raw_and_fetched_at() -> list[sa.Column]:
    return [
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _zero(name: str, type_: sa.types.TypeEngine) -> sa.Column:
    return sa.Column(name, type_, server_default="0", nullable=False)


def upgrade() -> None:
    op.create_table(
        "ml_ads_campaigns",
        sa.Column("advertiser_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("strategy", sa.String(30), nullable=True),
        sa.Column("channel", sa.String(30), nullable=True),
        sa.Column("budget", sa.Numeric(16, 2), nullable=True),
        sa.Column("daily_budget", sa.Numeric(16, 2), nullable=True),
        sa.Column("automatic_budget", sa.Boolean(), nullable=True),
        sa.Column("acos_target", sa.Numeric(10, 2), nullable=True),
        sa.Column("acos_top_search_target", sa.Numeric(10, 2), nullable=True),
        sa.Column("roas_target", sa.Numeric(10, 2), nullable=True),
        sa.Column("salesforce_event_id", sa.BigInteger(), nullable=True),
        sa.Column("date_created", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
        *_raw_and_fetched_at(),
        sa.PrimaryKeyConstraint("advertiser_id", "campaign_id"),
    )
    op.create_table(
        "ml_ads_campaign_days",
        sa.Column("advertiser_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        _zero("cost", sa.Numeric(16, 2)),
        _zero("direct_amount", sa.Numeric(16, 2)),
        _zero("indirect_amount", sa.Numeric(16, 2)),
        _zero("organic_amount", sa.Numeric(16, 2)),
        _zero("clicks", sa.Integer()),
        _zero("prints", sa.BigInteger()),
        _zero("direct_units", sa.Integer()),
        _zero("indirect_units", sa.Integer()),
        _zero("units_quantity", sa.Integer()),
        _zero("organic_units", sa.Integer()),
        *_raw_and_fetched_at(),
        sa.PrimaryKeyConstraint("advertiser_id", "campaign_id", "day"),
    )


def downgrade() -> None:
    op.drop_table("ml_ads_campaign_days")
    op.drop_table("ml_ads_campaigns")
