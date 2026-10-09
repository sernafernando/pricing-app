"""ml_ads_display_campaign_days + ml_ads_brand_days (ml-billing-balance PR 3)

Revision ID: 20261014_ml_ads_account_level
Revises: 20261013_ml_billing_sweep_gaps
Create Date: 2026-10-09

Account-level ads facts (design "Schema", slice 3): Display per campaign per day and Brand Ads per
advertiser per day. No cached sums (ADS-4). Downgrade drops exactly these two tables.

down_revision must be the single alembic head of origin/main at merge; re-chain it if main advanced.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261014_ml_ads_account_level"
down_revision: Union[str, None] = "20261013_ml_billing_sweep_gaps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_ads_display_campaign_days",
        sa.Column("advertiser_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("consumed_budget", sa.Numeric(16, 2), server_default="0", nullable=False),
        sa.Column("prints", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reach", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("advertiser_id", "campaign_id", "day"),
    )
    op.create_table(
        "ml_ads_brand_days",
        sa.Column("advertiser_id", sa.BigInteger(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("cost", sa.Numeric(16, 2), nullable=True),
        sa.Column("prints", sa.BigInteger(), nullable=True),
        sa.Column("clicks", sa.Integer(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("advertiser_id", "day"),
    )


def downgrade() -> None:
    op.drop_table("ml_ads_brand_days")
    op.drop_table("ml_ads_display_campaign_days")
