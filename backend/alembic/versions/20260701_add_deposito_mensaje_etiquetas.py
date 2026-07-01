"""Agregar manual_deposito_mensaje a etiquetas_envio

Revision ID: 20260701_deposito_msg
Revises: 20260626_create_tplink_ventas_metricas
Create Date: 2026-07-01

"""

from alembic import op
import sqlalchemy as sa

revision = "20260701_deposito_msg"
down_revision = "20260626_create_tplink_ventas_metricas"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("etiquetas_envio", sa.Column("manual_deposito_mensaje", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("etiquetas_envio", "manual_deposito_mensaje")
