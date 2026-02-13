"""Crear tablas logisticas y etiquetas_envio para gestión de envíos flex

Revision ID: 20260213_etiquetas_log
Revises: 20260213_cp_cordones
Create Date: 2026-02-13

"""

from alembic import op
import sqlalchemy as sa

revision = "20260213_etiquetas_log"
down_revision = "20260213_cp_cordones"
branch_labels = None
depends_on = None


def upgrade():
    # Tabla logisticas
    op.create_table(
        "logisticas",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_logisticas_id", "logisticas", ["id"])
    op.create_index("ix_logisticas_nombre", "logisticas", ["nombre"], unique=True)

    # Tabla etiquetas_envio
    op.create_table(
        "etiquetas_envio",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("shipping_id", sa.String(50), nullable=False),
        sa.Column("sender_id", sa.BigInteger(), nullable=True),
        sa.Column("hash_code", sa.Text(), nullable=True),
        sa.Column("nombre_archivo", sa.String(255), nullable=True),
        sa.Column("fecha_envio", sa.Date(), nullable=False),
        sa.Column("logistica_id", sa.Integer(), nullable=True),
        sa.Column("pistoleado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pistoleado_caja", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["logistica_id"], ["logisticas.id"]),
    )
    op.create_index("ix_etiquetas_envio_id", "etiquetas_envio", ["id"])
    op.create_index("ix_etiquetas_envio_shipping_id", "etiquetas_envio", ["shipping_id"], unique=True)
    op.create_index("idx_etiquetas_envio_fecha", "etiquetas_envio", ["fecha_envio"])
    op.create_index("idx_etiquetas_envio_logistica", "etiquetas_envio", ["logistica_id"])


def downgrade():
    op.drop_index("idx_etiquetas_envio_logistica", table_name="etiquetas_envio")
    op.drop_index("idx_etiquetas_envio_fecha", table_name="etiquetas_envio")
    op.drop_index("ix_etiquetas_envio_shipping_id", table_name="etiquetas_envio")
    op.drop_index("ix_etiquetas_envio_id", table_name="etiquetas_envio")
    op.drop_table("etiquetas_envio")

    op.drop_index("ix_logisticas_nombre", table_name="logisticas")
    op.drop_index("ix_logisticas_id", table_name="logisticas")
    op.drop_table("logisticas")
