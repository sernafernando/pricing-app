"""promo refresh on reactivation: create promo_refresh_reactivation queue

Revision ID: 20261018_promo_refresh_reactivation
Revises: 20261017_ml_items_installments_campaign
Create Date: 2026-10-14

Queue fed by the ML publications store when a publication becomes active again and drained by the
`ml_publications.promo_refresh` worker handler. Separate from `promo_refresh_pending` (panel write path).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261018_promo_refresh_reactivation"
down_revision: Union[str, None] = "20261017_ml_items_installments_campaign"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promo_refresh_reactivation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mla", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mla", name="uq_promo_refresh_reactivation_mla"),
    )
    op.create_index("ix_promo_refresh_reactivation_due_at", "promo_refresh_reactivation", ["due_at"])


def downgrade() -> None:
    op.drop_index("ix_promo_refresh_reactivation_due_at", table_name="promo_refresh_reactivation")
    op.drop_table("promo_refresh_reactivation")
