"""Agregar flag es_turbo a etiquetas_envio

Los envíos Turbo de MercadoLibre (mlshipping_method_id = '515282') se
detectan durante el enriquecimiento y se marcan con este boolean.
Permite badge visual, filtro en tabla y cálculo de costo diferenciado.

Revision ID: 20260220_es_turbo
Revises: 20260220_es_outlet
Create Date: 2026-02-20

"""

from alembic import op
import sqlalchemy as sa

revision = "20260220_es_turbo"
down_revision = "20260220_es_outlet"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "etiquetas_envio",
        sa.Column("es_turbo", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index("idx_etiquetas_envio_es_turbo", "etiquetas_envio", ["es_turbo"])


def downgrade():
    op.drop_index("idx_etiquetas_envio_es_turbo", table_name="etiquetas_envio")
    op.drop_column("etiquetas_envio", "es_turbo")
