"""Agregar flag es_outlet a etiquetas_envio

El enriquecimiento background ahora detecta si algún item del envío
contiene "outlet" en el título (shipping_items[].description del ML webhook).
Se guarda como boolean para badge visual y filtro rápido en el frontend.

Revision ID: 20260220_es_outlet
Revises: 20260219_tienda_asig
Create Date: 2026-02-20

"""

from alembic import op
import sqlalchemy as sa

revision = "20260220_es_outlet"
down_revision = "20260219_tienda_asig"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "etiquetas_envio",
        sa.Column("es_outlet", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index("idx_etiquetas_envio_es_outlet", "etiquetas_envio", ["es_outlet"])


def downgrade():
    op.drop_index("idx_etiquetas_envio_es_outlet", table_name="etiquetas_envio")
    op.drop_column("etiquetas_envio", "es_outlet")
