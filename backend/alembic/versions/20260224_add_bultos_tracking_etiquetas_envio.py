"""add total_bultos and pistoleado_bultos to etiquetas_envio

Revision ID: 20260224_bultos
Revises: 20260224_creado_por
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa

revision = "20260224_bultos"
down_revision = "20260224_creado_por"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "etiquetas_envio",
        sa.Column("total_bultos", sa.Integer(), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("pistoleado_bultos", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("etiquetas_envio", "pistoleado_bultos")
    op.drop_column("etiquetas_envio", "total_bultos")
