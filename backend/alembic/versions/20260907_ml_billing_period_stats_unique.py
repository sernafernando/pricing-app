"""ml-ventas-desglose-costos corte 3: unique constraint on
ml_billing_period_stats.period_key

Revision ID: 20260907_ml_billing_period_stats_unique
Revises: 20260904_ml_shipments_ops_costs
Create Date: 2026-09-07

Debt from corte 1: `ml_billing_period_stats` shipped without a uniqueness
constraint on `period_key` because it had no writer yet. Corte 3 (the
daily billing sweep) upserts one stat row per period on every daily
run; without this constraint the upsert would accumulate duplicate rows
on every re-run instead of updating the existing one.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260907_ml_billing_period_stats_unique"
down_revision: Union[str, None] = "20260904_ml_shipments_ops_costs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_ml_billing_period_stats_period_key",
        "ml_billing_period_stats",
        ["period_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ml_billing_period_stats_period_key",
        "ml_billing_period_stats",
        type_="unique",
    )
