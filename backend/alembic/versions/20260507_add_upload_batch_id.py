"""Agregar upload_batch_id a etiquetas_colecta

Cada operación de subida de ZPLs (un POST con N archivos) genera un UUID
que se asigna a TODAS las etiquetas insertadas en esa operación.

Permite identificar un "lote de carga" para que el operador pueda seleccionar
todas las etiquetas que subió junto con un mismo upload (caso de uso: cargué
ZPLs en la colecta equivocada y necesito seleccionar todo lo de ese lote para
reasignar/borrar).

Nullable: las etiquetas legacy (pre-feature) y las creadas por scan individual
no tienen lote.

Revision ID: 20260507_batch_id
Revises: 20260507_legacy_pending
Create Date: 2026-05-07

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260507_batch_id"
down_revision = "20260507_legacy_pending"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "etiquetas_colecta",
        sa.Column("upload_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_etiquetas_colecta_upload_batch_id",
        "etiquetas_colecta",
        ["upload_batch_id"],
    )


def downgrade():
    op.drop_index("ix_etiquetas_colecta_upload_batch_id", table_name="etiquetas_colecta")
    op.drop_column("etiquetas_colecta", "upload_batch_id")
