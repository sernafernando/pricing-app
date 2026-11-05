"""ml_ads_campaign_contributions.deleted_at / deleted_by_id: deleting an aporte is soft (ml-ads-aportes-robust S6)

Revision ID: 20261231_ml_ads_contribution_soft_delete
Revises: 20261105_tacticals
Create Date: 2026-11-04

A deleted aporte keeps its row, marked with who removed it and when; every read ignores it. Both columns are set
together or not at all. Rows loaded before these columns stay live. The table is small (rows loaded by hand), so
plain ALTERs.

Downgrade refuses while a deleted aporte exists: dropping the columns would bring it back into the Métricas ML figures.
Remove those rows by hand first (their `auditoria` rows keep what they were).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261231_ml_ads_contribution_soft_delete"
down_revision: Union[str, None] = "20261105_tacticals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_ads_campaign_contributions"
CK_DELETED = "ck_ml_ads_campaign_contributions_deleted"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("deleted_by_id", sa.Integer(), nullable=True))
    op.create_check_constraint(CK_DELETED, TABLE, "(deleted_at IS NULL) = (deleted_by_id IS NULL)")


def downgrade() -> None:
    deleted = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {TABLE} WHERE deleted_at IS NOT NULL")).scalar_one()
    if deleted:
        raise RuntimeError(
            f"{deleted} deleted contribution(s) in {TABLE}: downgrading would bring them back into the figures. "
            "Remove them by hand (their auditoria rows keep what they were) and run the downgrade again."
        )
    op.drop_constraint(CK_DELETED, TABLE, type_="check")
    op.drop_column(TABLE, "deleted_by_id")
    op.drop_column(TABLE, "deleted_at")
