"""Agregar latitud/longitud a transportes para geocodificación

Revision ID: 20260227_transp_geo
Revises: 20260226_man_phone
Create Date: 2026-02-27

"""

from alembic import op
import sqlalchemy as sa

revision = "20260227_transp_geo"
down_revision = "20260226_man_phone"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("transportes", sa.Column("latitud", sa.Float(), nullable=True))
    op.add_column("transportes", sa.Column("longitud", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("transportes", "longitud")
    op.drop_column("transportes", "latitud")
