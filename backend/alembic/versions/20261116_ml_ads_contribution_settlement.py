"""ml_ads_campaign_contributions.settlement (ml-ads-brand-contribution T1c)

Revision ID: 20261116_ml_ads_contribution_settlement
Revises: 20261115_sell_in_bono_queue_alcance
Create Date: 2026-10-23

A fixed amount says how it settles: `full` (the brand pays it whole, whatever the campaign spent) or
`refund_difference` (it counts only up to what the campaign spent; the rest goes back to the brand). A percentage
has none. Fixed amounts loaded before this column are backfilled `refund_difference`, which never overstates
profit. No Métricas ML number reads it yet (T2).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261116_ml_ads_contribution_settlement"
down_revision: Union[str, None] = "20261115_sell_in_bono_queue_alcance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_ads_campaign_contributions"
CK_VALUES = "ck_ml_ads_campaign_contributions_settlement"
CK_KIND = "ck_ml_ads_campaign_contributions_settlement_kind"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("settlement", sa.String(24), nullable=True))
    op.execute(f"UPDATE {TABLE} SET settlement = 'refund_difference' WHERE kind = 'fixed_amount'")
    op.create_check_constraint(CK_VALUES, TABLE, "settlement IN ('full', 'refund_difference')")
    op.create_check_constraint(CK_KIND, TABLE, "(kind = 'fixed_amount') = (settlement IS NOT NULL)")


def downgrade() -> None:
    op.drop_constraint(CK_KIND, TABLE, type_="check")
    op.drop_constraint(CK_VALUES, TABLE, type_="check")
    op.drop_column(TABLE, "settlement")
