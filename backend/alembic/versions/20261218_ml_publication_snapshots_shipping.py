"""Add shipping fields to ml_publication_snapshots

Revision ID: 20261218_ml_pub_snapshots_shipping
Revises: 20261228_ml_pay_ops_coupon_idx
Create Date: 2026-11-02

Persists shipping.mode / logistic_type / local_pick_up / free_shipping /
store_pick_up / tags from the ML item body so repair jobs can detect drift
from DB without re-fetching a template MLA each run.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261218_ml_pub_snapshots_shipping"
down_revision: Union[str, None] = "20261228_ml_pay_ops_coupon_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_publication_snapshots", sa.Column("shipping_mode", sa.String(length=50), nullable=True))
    op.add_column("ml_publication_snapshots", sa.Column("logistic_type", sa.String(length=50), nullable=True))
    op.add_column("ml_publication_snapshots", sa.Column("local_pick_up", sa.Boolean(), nullable=True))
    op.add_column("ml_publication_snapshots", sa.Column("free_shipping", sa.Boolean(), nullable=True))
    op.add_column("ml_publication_snapshots", sa.Column("store_pick_up", sa.Boolean(), nullable=True))
    op.add_column("ml_publication_snapshots", sa.Column("shipping_tags", JSONB(), nullable=True))
    op.create_index(
        "ix_ml_publication_snapshots_logistic_type",
        "ml_publication_snapshots",
        ["logistic_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ml_publication_snapshots_logistic_type", table_name="ml_publication_snapshots")
    op.drop_column("ml_publication_snapshots", "shipping_tags")
    op.drop_column("ml_publication_snapshots", "store_pick_up")
    op.drop_column("ml_publication_snapshots", "free_shipping")
    op.drop_column("ml_publication_snapshots", "local_pick_up")
    op.drop_column("ml_publication_snapshots", "logistic_type")
    op.drop_column("ml_publication_snapshots", "shipping_mode")
