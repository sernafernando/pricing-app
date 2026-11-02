"""ml_ads_display_campaigns (ml-ads-cupones-display T1)

Revision ID: 20261226_ml_ads_display_catalog
Revises: 20261217_drop_sell_in_compras_pedido_compra_id
Create Date: 2026-11-02

The latest Display campaign catalog (name, type, status, goal, site, dates and the raw list entry), stored by
the Display day step from `display/campaigns`. Downgrade drops exactly this table.

down_revision must be the single alembic head of origin/main at merge; re-chain it if main advanced.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261226_ml_ads_display_catalog"
down_revision: Union[str, None] = "20261217_drop_sell_in_compras_pedido_compra_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_ads_display_campaigns",
        sa.Column("advertiser_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("type", sa.String(40), nullable=True),
        sa.Column("status", sa.String(40), nullable=True),
        sa.Column("goal", sa.String(40), nullable=True),
        sa.Column("site_id", sa.String(10), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("advertiser_id", "campaign_id"),
    )


def downgrade() -> None:
    op.drop_table("ml_ads_display_campaigns")
