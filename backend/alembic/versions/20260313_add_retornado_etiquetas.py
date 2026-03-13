"""Agregar campos retornado a etiquetas_envio

Permite marcar envíos como "retornado" cuando el paquete fue devuelto
físicamente a la oficina. Es independiente del sistema de flags:
un envío puede estar flaggeado Y retornado simultáneamente.

Columnas:
- retornado: boolean (NULL = no retornado)
- retornado_at: timestamp de cuándo se marcó
- retornado_usuario_id: FK a usuarios.id (quién lo marcó)

Revision ID: 20260313_retornado
Revises: 20260313_rrhh_fichadas_null_emp
Create Date: 2026-03-13

"""

import sqlalchemy as sa
from alembic import op

revision = "20260313_retornado"
down_revision = "20260313_rrhh_fichadas_null_emp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "etiquetas_envio",
        sa.Column("retornado", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column(
            "retornado_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column(
            "retornado_usuario_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_etiquetas_envio_retornado",
        "etiquetas_envio",
        ["retornado"],
    )


def downgrade() -> None:
    op.drop_index("idx_etiquetas_envio_retornado", table_name="etiquetas_envio")
    op.drop_column("etiquetas_envio", "retornado_usuario_id")
    op.drop_column("etiquetas_envio", "retornado_at")
    op.drop_column("etiquetas_envio", "retornado")
