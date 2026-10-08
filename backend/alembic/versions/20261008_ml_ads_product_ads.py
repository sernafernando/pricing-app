"""ml_ads_day_ledger + ml_ads_ad_group_days + ml_ads_item_days (ml-billing-balance PR 1a)

Revision ID: 20261008_ml_ads_product_ads
Revises: 20261010_ml_user_product_stock_locations
Create Date: 2026-10-08

Inert foundation: three tables for Product Ads facts by ad day (design "Schema", slice 1). Nothing
reads or writes them yet. No cached sums are stored (ADS-4). Downgrade drops exactly these tables.

down_revision must be the single alembic head of origin/main at merge; re-chain it if main advanced.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261008_ml_ads_product_ads"
down_revision: Union[str, None] = "20261010_ml_user_product_stock_locations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_ads_day_ledger",
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("advertiser_id", sa.BigInteger(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("groups_offset", sa.Integer(), server_default="0", nullable=False),
        sa.Column("summary_cost", sa.Numeric(16, 2), nullable=True),
        sa.Column("summary_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempts_day", sa.Date(), nullable=True),
        sa.Column("mismatch_laps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("fetch_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("final", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(
            "status IN ('fetching', 'refetch', 'closed', 'mismatch', 'error', 'unavailable')",
            name="ck_ml_ads_day_ledger_status",
        ),
        sa.PrimaryKeyConstraint("source", "advertiser_id", "day"),
    )
    op.create_index(
        "ix_ml_ads_day_ledger_open",
        "ml_ads_day_ledger",
        ["source", "status"],
        postgresql_where=sa.text("status <> 'closed'"),
    )

    op.create_table(
        "ml_ads_ad_group_days",
        sa.Column("advertiser_id", sa.BigInteger(), nullable=False),
        sa.Column("ad_group_id", sa.BigInteger(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("ad_group_type", sa.String(length=20), nullable=True),
        sa.Column("external_id", sa.String(length=40), nullable=True),
        sa.Column("cost", sa.Numeric(16, 2), nullable=True),
        sa.Column("direct_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("indirect_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("clicks", sa.Integer(), nullable=True),
        sa.Column("prints", sa.BigInteger(), nullable=True),
        sa.Column("units_quantity", sa.Integer(), nullable=True),
        sa.Column("drill_status", sa.String(length=10), nullable=False),
        sa.Column("ads_offset", sa.Integer(), server_default="0", nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "drill_status IN ('not_needed', 'pending', 'done', 'mismatch')",
            name="ck_ml_ads_ad_group_days_drill_status",
        ),
        sa.PrimaryKeyConstraint("advertiser_id", "ad_group_id", "day"),
    )
    op.create_index(
        "ix_ml_ads_ad_group_days_adv_day_drill",
        "ml_ads_ad_group_days",
        ["advertiser_id", "day", "drill_status"],
    )

    op.create_table(
        "ml_ads_item_days",
        sa.Column("advertiser_id", sa.BigInteger(), nullable=False),
        sa.Column("ad_group_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.String(length=30), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("cost", sa.Numeric(16, 2), server_default="0", nullable=False),
        sa.Column("direct_amount", sa.Numeric(16, 2), server_default="0", nullable=False),
        sa.Column("indirect_amount", sa.Numeric(16, 2), server_default="0", nullable=False),
        sa.Column("organic_amount", sa.Numeric(16, 2), server_default="0", nullable=False),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("direct_units", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indirect_units", sa.Integer(), server_default="0", nullable=False),
        sa.Column("organic_units", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prints", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("advertiser_id", "ad_group_id", "item_id", "day"),
    )
    op.create_index("ix_ml_ads_item_days_day_item", "ml_ads_item_days", ["day", "item_id"])


def downgrade() -> None:
    op.drop_index("ix_ml_ads_item_days_day_item", table_name="ml_ads_item_days")
    op.drop_table("ml_ads_item_days")
    op.drop_index("ix_ml_ads_ad_group_days_adv_day_drill", table_name="ml_ads_ad_group_days")
    op.drop_table("ml_ads_ad_group_days")
    op.drop_index("ix_ml_ads_day_ledger_open", table_name="ml_ads_day_ledger")
    op.drop_table("ml_ads_day_ledger")
