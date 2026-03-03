"""Crear tabla etiquetas_colecta para checkeo de colecta

Tabla simplificada para cargar ZPL de colecta y verificar
estados ERP y ML. Separada de etiquetas_envio (flex).

Revision ID: 20260303_etiq_colecta
Revises: 20260302_rma_seg
Create Date: 2026-03-03

"""

from alembic import op
import sqlalchemy as sa

revision = "20260303_etiq_colecta"
down_revision = "20260302_rma_seg"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "etiquetas_colecta",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shipping_id", sa.String(50), unique=True, nullable=False),
        sa.Column("sender_id", sa.BigInteger(), nullable=True),
        sa.Column("hash_code", sa.Text(), nullable=True),
        sa.Column("nombre_archivo", sa.String(255), nullable=True),
        sa.Column("fecha_carga", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_etiquetas_colecta_shipping_id",
        "etiquetas_colecta",
        ["shipping_id"],
        unique=True,
    )
    op.create_index(
        "idx_etiquetas_colecta_fecha",
        "etiquetas_colecta",
        ["fecha_carga"],
    )


def downgrade():
    op.drop_index("idx_etiquetas_colecta_fecha", table_name="etiquetas_colecta")
    op.drop_index(
        "ix_etiquetas_colecta_shipping_id", table_name="etiquetas_colecta"
    )
    op.drop_table("etiquetas_colecta")
