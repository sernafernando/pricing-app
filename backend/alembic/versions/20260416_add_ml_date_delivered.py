"""add ml_date_delivered to etiquetas_envio

Revision ID: 20260416_date_delivered
Revises: 20260413_seed_sug
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260416_date_delivered"
down_revision = "20260413_seed_sug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "etiquetas_envio",
        sa.Column("ml_date_delivered", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("etiquetas_envio", "ml_date_delivered")
