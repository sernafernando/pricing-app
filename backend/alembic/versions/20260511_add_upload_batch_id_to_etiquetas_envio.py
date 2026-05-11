"""Agregar upload_batch_id a etiquetas_envio

Cada operación de subida de ZPLs (un POST /etiquetas-envio/upload) genera un
UUID que se asigna a TODAS las etiquetas insertadas en esa operación.

Permite identificar un "lote de carga" para que el operador pueda seleccionar
todas las etiquetas que subió en un mismo upload (caso de uso: cargué ZPLs en
la fecha equivocada y necesito seleccionar todo lo del lote para cambiar la
fecha en masa).

Nullable: las etiquetas legacy (pre-feature), los envíos manuales y las
creadas por scan individual no tienen lote.

NO hay backfill: etiquetas existentes quedan con upload_batch_id = NULL.
El endpoint GET /etiquetas-envio/lotes filtra IS NOT NULL.

Revision ID: 20260511_add_batch_id_envio
Revises: 20260508_produccion_ver_combos
Create Date: 2026-05-11

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260511_add_batch_id_envio"
down_revision = "20260508_produccion_ver_combos"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "etiquetas_envio",
        sa.Column("upload_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_etiquetas_envio_upload_batch_id",
        "etiquetas_envio",
        ["upload_batch_id"],
    )


def downgrade():
    op.drop_index("ix_etiquetas_envio_upload_batch_id", table_name="etiquetas_envio")
    op.drop_column("etiquetas_envio", "upload_batch_id")
