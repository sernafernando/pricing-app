"""ml-billing-balance PR 4a-i: ml_billing_sweep_gaps

Revision ID: 20261013_ml_billing_sweep_gaps
Revises: 20261011_ml_billing_documents
Create Date: 2026-10-13

- `ml_billing_sweep_gaps`: the positions of the billing sweep that ML refused
  with a bare 400 and the sweep stepped over, one row per (period, document
  type, source, paging, position). Nothing derived is stored: completeness
  stays a query.

Downgrade drops the table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_ml_billing_sweep_gaps"
down_revision: Union[str, None] = "20261011_ml_billing_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ml_billing_sweep_gaps"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period_key", sa.String(10), nullable=False),
        sa.Column("document_type", sa.String(20), nullable=False),
        sa.Column("billing_source", sa.String(10), nullable=False),
        sa.Column("paging", sa.String(10), nullable=False),
        sa.Column("position", sa.String(30), nullable=False),
        sa.Column("window", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("seen_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lap_id", sa.String(40), nullable=True),
        sa.UniqueConstraint(
            "period_key",
            "document_type",
            "billing_source",
            "paging",
            "position",
            name="uq_ml_billing_sweep_gaps_position",
        ),
    )
    op.create_index("ix_ml_billing_sweep_gaps_period_key", _TABLE, ["period_key"])


def downgrade() -> None:
    op.drop_index("ix_ml_billing_sweep_gaps_period_key", table_name=_TABLE)
    op.drop_table(_TABLE)
