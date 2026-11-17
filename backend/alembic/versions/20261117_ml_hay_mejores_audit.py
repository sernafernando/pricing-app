"""ml_hay_mejores_audit — lean flag / Auto toggle events.

Revision ID: 20261117_ml_hay_mejores_audit
Revises: 20261117_ml_hay_mejores_criterios
Create Date: 2026-11-17

Append-only. No FK to ml_items (same sparse MLA key as criterios).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261117_ml_hay_mejores_audit"
down_revision: Union[str, None] = "20261117_ml_hay_mejores_criterios"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_hay_mejores_audit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ml_hay_mejores_audit_item_created",
        "ml_hay_mejores_audit",
        ["item_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ml_hay_mejores_audit_item_created", table_name="ml_hay_mejores_audit")
    op.drop_table("ml_hay_mejores_audit")
