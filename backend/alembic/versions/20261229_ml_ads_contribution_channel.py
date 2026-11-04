"""ml_ads_campaign_contributions.channel: a brand contribution for Display (ml-ads-display-contributions S2)

Revision ID: 20261229_ml_ads_contribution_channel
Revises: 20261224_gestion_full_envio_last_polled
Create Date: 2026-11-04

A contribution is for Product Ads (`product_ads`, every row loaded before this column) or for Display (`display`).
A Display contribution may leave `campaign_id` NULL: it covers the whole Display account of its advertiser. Only
Display may: a Product Ads contribution always names its campaign. The table is small (rows loaded by hand), so
plain ALTERs.

Downgrade refuses while a Display contribution exists: dropping the column would turn it into a Product Ads one
(money subtracted from the wrong ads), and deleting it would lose what a brand paid. Delete those rows by hand first.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261229_ml_ads_contribution_channel"
down_revision: Union[str, None] = "20261224_gestion_full_envio_last_polled"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_ads_campaign_contributions"
CK_CHANNEL = "ck_ml_ads_campaign_contributions_channel"
CK_CAMPAIGN = "ck_ml_ads_campaign_contributions_channel_campaign"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("channel", sa.String(16), nullable=False, server_default="product_ads"))
    op.create_check_constraint(CK_CHANNEL, TABLE, "channel IN ('product_ads', 'display')")
    op.alter_column(TABLE, "campaign_id", existing_type=sa.BigInteger(), nullable=True)
    op.create_check_constraint(CK_CAMPAIGN, TABLE, "campaign_id IS NOT NULL OR channel = 'display'")


def downgrade() -> None:
    display = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {TABLE} WHERE channel = 'display'")).scalar_one()
    if display:
        raise RuntimeError(
            f"{display} Display contribution(s) in {TABLE}: downgrading would turn them into Product Ads ones. "
            "Delete them by hand (after keeping what they record) and run the downgrade again."
        )
    op.drop_constraint(CK_CAMPAIGN, TABLE, type_="check")
    op.alter_column(TABLE, "campaign_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_constraint(CK_CHANNEL, TABLE, type_="check")
    op.drop_column(TABLE, "channel")
