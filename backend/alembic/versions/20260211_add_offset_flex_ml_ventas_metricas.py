"""Add offset_flex column to ml_ventas_metricas

Revision ID: 20260211_offset_flex_metricas
Revises: 20260211_cc_perm
Create Date: 2026-02-11

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260211_offset_flex_metricas"
down_revision = "20260211_cc_perm"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ml_ventas_metricas",
        sa.Column("offset_flex", sa.Numeric(18, 2), server_default="0", nullable=True),
    )


def downgrade():
    op.drop_column("ml_ventas_metricas", "offset_flex")
