"""promo-state-dynamic-refresh: create promo_refresh_pending retry queue

Revision ID: 20260720_add_promo_refresh_pending
Revises: 20260720_add_equipo_color_teams
Create Date: 2026-07-20

Backend slice (PR1) of the promo-state-dynamic-refresh change. Creates the
`promo_refresh_pending` table used by the write-path hook
(`_enqueue_refresh_retry` in `ml_promotions_write_service.py`) and the
drainer script (`app/scripts/drain_promo_refresh.py`) to reliably retry a
server-side point-refresh of the `ml_item_promotions` mirror ~60s after an
operator's own enroll/remove write.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_add_promo_refresh_pending"
down_revision: Union[str, None] = "20260720_add_equipo_color_teams"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promo_refresh_pending",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mla", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mla", name="uq_promo_refresh_pending_mla"),
    )
    op.create_index("ix_promo_refresh_pending_due_at", "promo_refresh_pending", ["due_at"])


def downgrade() -> None:
    op.drop_index("ix_promo_refresh_pending_due_at", table_name="promo_refresh_pending")
    op.drop_table("promo_refresh_pending")
