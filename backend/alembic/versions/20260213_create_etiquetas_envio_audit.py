"""Crear tabla etiquetas_envio_audit para auditoría de borrados

Antes de eliminar etiquetas, se copian acá con el usuario que las
borró, timestamp y comentario opcional.

Revision ID: 20260213_etiq_audit
Revises: 20260213_coords_etiq
Create Date: 2026-02-13

"""

from alembic import op
import sqlalchemy as sa

revision = "20260213_etiq_audit"
down_revision = "20260213_coords_etiq"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "etiquetas_envio_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shipping_id", sa.String(50), nullable=False, index=True),
        sa.Column("sender_id", sa.BigInteger(), nullable=True),
        sa.Column("hash_code", sa.Text(), nullable=True),
        sa.Column("nombre_archivo", sa.String(255), nullable=True),
        sa.Column("fecha_envio", sa.Date(), nullable=False),
        sa.Column("logistica_id", sa.Integer(), nullable=True),
        sa.Column("latitud", sa.Float(), nullable=True),
        sa.Column("longitud", sa.Float(), nullable=True),
        sa.Column("direccion_completa", sa.String(500), nullable=True),
        sa.Column("direccion_comentario", sa.String(500), nullable=True),
        sa.Column("pistoleado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pistoleado_caja", sa.String(50), nullable=True),
        sa.Column("original_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("delete_comment", sa.String(500), nullable=True),
    )

    op.create_index("idx_audit_shipping_id", "etiquetas_envio_audit", ["shipping_id"])
    op.create_index("idx_audit_deleted_at", "etiquetas_envio_audit", ["deleted_at"])
    op.create_index("idx_audit_deleted_by", "etiquetas_envio_audit", ["deleted_by"])


def downgrade():
    op.drop_table("etiquetas_envio_audit")
