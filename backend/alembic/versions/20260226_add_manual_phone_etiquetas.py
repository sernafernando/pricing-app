"""Agregar manual_phone a etiquetas_envio

Revision ID: 20260226_man_phone
Revises: 20260226_transp_loc
Create Date: 2026-02-26

"""

from alembic import op
import sqlalchemy as sa

revision = "20260226_man_phone"
down_revision = "20260226_transp_loc"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("etiquetas_envio", sa.Column("manual_phone", sa.String(100), nullable=True))


def downgrade():
    op.drop_column("etiquetas_envio", "manual_phone")
