"""sell_dirty queue drained by sell.drain

Revision ID: 20261031_sell_dirty_queue
Revises: 20261030_ml_write_log
Create Date: 2026-10-17

sell-in-sell-out T4. `sell_dirty` holds the sale lines whose sell-in /
sell-out allocation must be recomputed (`app/models/sell_dirty.py`). The
`sell.drain` handler drains it (inert until T5). The downgrade drops it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261031_sell_dirty_queue"
down_revision: Union[str, None] = "20261030_ml_write_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sell_dirty",
        sa.Column("canal", sa.String(length=8), nullable=False),
        sa.Column("venta_ref", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("canal IN ('ml', 'fuera', 'tn')", name="ck_sell_dirty_canal"),
        sa.PrimaryKeyConstraint("canal", "venta_ref"),
    )


def downgrade() -> None:
    op.drop_table("sell_dirty")
