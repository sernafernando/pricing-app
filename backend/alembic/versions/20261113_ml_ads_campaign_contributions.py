"""ml_ads_campaign_contributions (ml-ads-brand-contribution T1a)

Revision ID: 20261113_ml_ads_campaign_contributions
Revises: 20261112_sell_in_compras_porcentaje
Create Date: 2026-10-22

A brand's contribution to a Product Ads campaign over a date range the team loads: a percentage or a fixed amount.
New table only; nothing writes it yet (T1b adds the write API and its permission) and no Métricas ML number reads it
(T2).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_ml_ads_campaign_contributions"
down_revision: Union[str, None] = "20261112_sell_in_compras_porcentaje"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_ads_campaign_contributions"
INDEX = "ix_ml_ads_campaign_contributions_campaign"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("advertiser_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value", sa.Numeric(16, 2), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("brand", sa.String(120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('percentage', 'fixed_amount')", name="ck_ml_ads_campaign_contributions_kind"),
        sa.CheckConstraint(
            "value > 0 AND (kind <> 'percentage' OR value <= 100)", name="ck_ml_ads_campaign_contributions_value"
        ),
        sa.CheckConstraint("date_from <= date_to", name="ck_ml_ads_campaign_contributions_dates"),
    )
    op.create_index(INDEX, TABLE, ["advertiser_id", "campaign_id"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
    op.drop_table(TABLE)
