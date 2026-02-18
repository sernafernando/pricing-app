"""Agregar pistoleado_operador_id a etiquetas_envio y etiquetas_envio_audit

El módulo de pistoleado necesita registrar qué operador escaneó cada paquete.
Se agrega FK a operadores + index para queries de stats por operador.

Revision ID: 20260218_pistoleado_op
Revises: 20260213_operadores
Create Date: 2026-02-18

"""

from alembic import op
import sqlalchemy as sa

revision = "20260218_pistoleado_op"
down_revision = "20260213_operadores"
branch_labels = None
depends_on = None


def upgrade():
    # etiquetas_envio: agregar FK al operador que pistoleó
    op.add_column(
        "etiquetas_envio",
        sa.Column("pistoleado_operador_id", sa.Integer(), sa.ForeignKey("operadores.id"), nullable=True),
    )
    op.create_index(
        "idx_etiquetas_pistoleado_operador", "etiquetas_envio", ["pistoleado_operador_id"],
    )

    # etiquetas_envio_audit: agregar campo espejo (sin FK, es audit)
    op.add_column(
        "etiquetas_envio_audit",
        sa.Column("pistoleado_operador_id", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_index("idx_etiquetas_pistoleado_operador", table_name="etiquetas_envio")
    op.drop_column("etiquetas_envio", "pistoleado_operador_id")
    op.drop_column("etiquetas_envio_audit", "pistoleado_operador_id")
