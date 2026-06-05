"""Add is_cancelled + fecha_cancelacion to ml_ventas_metricas

Permite que la reconciliación de cancelaciones (cruce cross-DB contra
mlwebhook.ml_cancelled_orders) marque las ventas canceladas sin borrar la fila,
y que el dashboard las filtre al leer (is_cancelled = False).

Revision ID: 20260605_ml_cancel_metricas
Revises: 20260601_02_consultas_ver_mi_ranking_permiso
Create Date: 2026-06-05

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260605_ml_cancel_metricas"
down_revision = "20260601_02_consultas_ver_mi_ranking_permiso"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ml_ventas_metricas",
        sa.Column("is_cancelled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "ml_ventas_metricas",
        sa.Column("fecha_cancelacion", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ml_ventas_metricas_is_cancelled",
        "ml_ventas_metricas",
        ["is_cancelled"],
    )


def downgrade():
    op.drop_index("ix_ml_ventas_metricas_is_cancelled", table_name="ml_ventas_metricas")
    op.drop_column("ml_ventas_metricas", "fecha_cancelacion")
    op.drop_column("ml_ventas_metricas", "is_cancelled")
