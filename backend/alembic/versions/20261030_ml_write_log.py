"""ml_write_log: who made each write to ML (eventos-historial-legibles T2)

Revision ID: 20261030_ml_write_log
Revises: 20261029_tp_cost_fill_queue
Create Date: 2026-10-16

One row per write to ML that ML confirmed (promotion enroll/remove first), with
the acting user (NULL for system/worker writes). Indexed by (mla, created_at)
for the per-item panel. Downgrade drops exactly this table.

down_revision must be the single alembic head of origin/main at merge; re-chain it if main advanced.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261030_ml_write_log"
down_revision: Union[str, None] = "20261029_tp_cost_fill_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_write_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mla", sa.String(32), nullable=False),
        sa.Column("resource", sa.String(40), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=True),
        sa.Column("promotion_type", sa.String(40), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_ml_write_log_mla_created_at", "ml_write_log", ["mla", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ml_write_log_mla_created_at", table_name="ml_write_log")
    op.drop_table("ml_write_log")
