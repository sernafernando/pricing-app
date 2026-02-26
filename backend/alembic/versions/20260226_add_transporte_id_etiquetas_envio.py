"""Agregar transporte_id a etiquetas_envio

Revision ID: 20260226_transp_fk
Revises: 20260226_transp
Create Date: 2026-02-26

"""

from alembic import op
import sqlalchemy as sa

revision = "20260226_transp_fk"
down_revision = "20260226_transp"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "etiquetas_envio",
        sa.Column("transporte_id", sa.Integer(), sa.ForeignKey("transportes.id"), nullable=True),
    )
    op.create_index("idx_etiquetas_envio_transporte", "etiquetas_envio", ["transporte_id"])


def downgrade():
    op.drop_index("idx_etiquetas_envio_transporte", table_name="etiquetas_envio")
    op.drop_column("etiquetas_envio", "transporte_id")
