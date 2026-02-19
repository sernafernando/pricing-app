"""Agregar columna costo_override a etiquetas_envio

Permite pisar el costo calculado automáticamente (logistica_costo_cordon)
con un valor manual por etiqueta. Útil para envíos con costo especial.

Revision ID: 20260219_costo_override
Revises: 20260218_oculta_subcats
Create Date: 2026-02-19

"""

from alembic import op
import sqlalchemy as sa

revision = "20260219_costo_override"
down_revision = "20260218_oculta_subcats"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "etiquetas_envio",
        sa.Column("costo_override", sa.Numeric(12, 2), nullable=True),
    )


def downgrade():
    op.drop_column("etiquetas_envio", "costo_override")
