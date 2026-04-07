"""Add fecha_documento to rrhh_documentos

Fecha de emisión del documento, independiente de la fecha de vencimiento.
Permite registrar cuándo se emitió un preocupacional, certificado, etc.

Revision ID: 20260407_doc_fecha
Revises: 20260406_empresas
Create Date: 2026-04-07
"""

import sqlalchemy as sa
from alembic import op

revision = "20260407_doc_fecha"
down_revision = "20260406_empresas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rrhh_documentos", sa.Column("fecha_documento", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("rrhh_documentos", "fecha_documento")
