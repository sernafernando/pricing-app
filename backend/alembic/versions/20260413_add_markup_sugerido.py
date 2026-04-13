"""add markup_sugerido to markups_tienda_brand and markups_tienda_producto

Revision ID: 20260413_markup_sug
Revises: 20260410_perf_idx
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260413_markup_sug"
down_revision = "20260410_perf_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "markups_tienda_brand",
        sa.Column("markup_sugerido", sa.Float(), nullable=True),
    )
    op.add_column(
        "markups_tienda_producto",
        sa.Column("markup_sugerido", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("markups_tienda_producto", "markup_sugerido")
    op.drop_column("markups_tienda_brand", "markup_sugerido")
