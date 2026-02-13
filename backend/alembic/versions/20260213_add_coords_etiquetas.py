"""Agregar latitud, longitud, direccion_completa y direccion_comentario a etiquetas_envio

Para enriquecimiento con datos del ML webhook (coordenadas exactas del
destinatario, dirección formateada y comentarios del comprador como
"puerta negra", "timbre 3B", etc.).

Revision ID: 20260213_coords_etiq
Revises: 20260213_etiquetas_log
Create Date: 2026-02-13

"""

from alembic import op
import sqlalchemy as sa

revision = "20260213_coords_etiq"
down_revision = "20260213_etiquetas_log"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("etiquetas_envio", sa.Column("latitud", sa.Float(), nullable=True))
    op.add_column("etiquetas_envio", sa.Column("longitud", sa.Float(), nullable=True))
    op.add_column(
        "etiquetas_envio",
        sa.Column("direccion_completa", sa.String(500), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("direccion_comentario", sa.String(500), nullable=True),
    )


def downgrade():
    op.drop_column("etiquetas_envio", "direccion_comentario")
    op.drop_column("etiquetas_envio", "direccion_completa")
    op.drop_column("etiquetas_envio", "longitud")
    op.drop_column("etiquetas_envio", "latitud")
