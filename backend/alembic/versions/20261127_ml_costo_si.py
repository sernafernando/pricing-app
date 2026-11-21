"""ML sale costs at costo SI: the re-freeze queue and the backups of every re-frozen row

Revision ID: 20261127_ml_costo_si
Revises: 20261126_costo_si_moneda
Create Date: 2026-11-20

sell-in-costo-si T3 PR 7 (owner L15: a costo SI change re-costs every later sale, backup first). A costo SI recompute
queues the product and its combos in `ml_costo_si_dirty`; `sell.drain` re-freezes their ML sales from that date and
keeps each replaced `ml_order_item_costos` row in `ml_order_item_costos_backups`. Both start empty: nothing existing
is rewritten by this migration. The downgrade drops both tables.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261127_ml_costo_si"
down_revision: Union[str, None] = "20261126_costo_si_moneda"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ml_costo_si_dirty",
        sa.Column("producto_item_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("desde", sa.Date(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_table(
        "ml_order_item_costos_backups",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("costo_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.String(20), nullable=False),
        sa.Column("variation_id", sa.BigInteger(), nullable=True),
        sa.Column("fila", postgresql.JSONB(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("desde", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ml_order_item_costos_backups_costo", "ml_order_item_costos_backups", ["costo_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ml_order_item_costos_backups_costo", table_name="ml_order_item_costos_backups")
    op.drop_table("ml_order_item_costos_backups")
    op.drop_table("ml_costo_si_dirty")
