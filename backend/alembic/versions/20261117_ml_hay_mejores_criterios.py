"""ml_hay_mejores_criterios — per-MLA application criteria for hay_mejores.

Revision ID: 20261117_ml_hay_mejores_criterios
Revises: 20261123_ml_publicaciones_presets
Create Date: 2026-11-17

Sparse policy row per MLA (no FK to ml_items). Defaults = all criteria off.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261117_ml_hay_mejores_criterios"
down_revision: Union[str, None] = "20261123_ml_publicaciones_presets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_hay_mejores_criterios",
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("c1_activo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("c1_markup_min", sa.Numeric(12, 4), nullable=True),
        sa.Column("c1_markup_max", sa.Numeric(12, 4), nullable=True),
        sa.Column("c2_activo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("c2_solo_markup_positivo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("auto_aplicacion", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "sellers_excluidos",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("item_id"),
    )


def downgrade() -> None:
    op.drop_table("ml_hay_mejores_criterios")
