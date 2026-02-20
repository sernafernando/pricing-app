"""Agregar costo_turbo a logistica_costo_cordon

Los envíos turbo (mlshipping_method_id='515282') pueden tener un costo
diferenciado por logística×cordón. Si costo_turbo es NULL, se usa el
costo normal. Si tiene valor, se usa cuando es_turbo=True.

Revision ID: 20260220_costo_turbo
Revises: 20260220_es_turbo
Create Date: 2026-02-20

"""

from alembic import op
import sqlalchemy as sa

revision = "20260220_costo_turbo"
down_revision = "20260220_es_turbo"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "logistica_costo_cordon",
        sa.Column("costo_turbo", sa.Numeric(12, 2), nullable=True),
    )


def downgrade():
    op.drop_column("logistica_costo_cordon", "costo_turbo")
