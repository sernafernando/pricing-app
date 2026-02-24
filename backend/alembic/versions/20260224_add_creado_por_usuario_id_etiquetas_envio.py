"""add creado_por_usuario_id to etiquetas_envio

Revision ID: 20260224_creado_por
Revises: 20260224_system_user
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa

revision = "20260224_creado_por"
down_revision = "20260224_system_user"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "etiquetas_envio",
        sa.Column("creado_por_usuario_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_etiquetas_envio_creado_por_usuario",
        "etiquetas_envio",
        "usuarios",
        ["creado_por_usuario_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint(
        "fk_etiquetas_envio_creado_por_usuario",
        "etiquetas_envio",
        type_="foreignkey",
    )
    op.drop_column("etiquetas_envio", "creado_por_usuario_id")
