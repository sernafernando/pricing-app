"""Crear tabla transportes para envíos interprovinciales

Revision ID: 20260226_transp
Revises: (ver cadena actual)
Create Date: 2026-02-26

"""

from alembic import op
import sqlalchemy as sa

revision = "20260226_transp"
down_revision = "20260225_rma_supplier_cn_pending"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "transportes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("nombre", sa.String(150), unique=True, nullable=False),
        sa.Column("cuit", sa.String(13), nullable=True),
        sa.Column("direccion", sa.String(500), nullable=True),
        sa.Column("telefono", sa.String(50), nullable=True),
        sa.Column("horario", sa.String(200), nullable=True),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_transportes_nombre", "transportes", ["nombre"])


def downgrade():
    op.drop_index("idx_transportes_nombre", table_name="transportes")
    op.drop_table("transportes")
