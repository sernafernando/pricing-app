"""Agregar flag de envío a etiquetas_envio

Permite marcar envíos como "mal_pasado", "envio_cancelado", "duplicado"
u "otro" sin borrarlos. Los envíos flaggeados se muestran con badge visual
y se excluyen del conteo operativo por defecto en TabEnviosFlex.

Columnas:
- flag_envio: tipo de flag (mal_pasado, envio_cancelado, duplicado, otro)
- flag_envio_motivo: observación libre (se muestra como tooltip)
- flag_envio_at: timestamp de cuándo se flaggeó
- flag_envio_usuario_id: FK a usuarios.id (quién lo flaggeó)

Revision ID: 20260309_flag_envio
Revises: 20260306_permiso_free_shipping
Create Date: 2026-03-09

"""

import sqlalchemy as sa
from alembic import op

revision = "20260309_flag_envio"
down_revision = "20260306_permiso_free_shipping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "etiquetas_envio",
        sa.Column("flag_envio", sa.String(50), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("flag_envio_motivo", sa.Text(), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column(
            "flag_envio_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column(
            "flag_envio_usuario_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_etiquetas_envio_flag",
        "etiquetas_envio",
        ["flag_envio"],
    )


def downgrade() -> None:
    op.drop_index("idx_etiquetas_envio_flag", table_name="etiquetas_envio")
    op.drop_column("etiquetas_envio", "flag_envio_usuario_id")
    op.drop_column("etiquetas_envio", "flag_envio_at")
    op.drop_column("etiquetas_envio", "flag_envio_motivo")
    op.drop_column("etiquetas_envio", "flag_envio")
