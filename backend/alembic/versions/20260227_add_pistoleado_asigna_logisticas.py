"""Agregar pistoleado_asigna a logisticas

Flag para que al pistolear con esta logística, en vez de verificar
coincidencia, asigne la logística a la etiqueta automáticamente.
Uso: logísticas de moto que no tienen etiquetas pre-asignadas.

Revision ID: 20260227_pist_asigna
Revises: 20260227_transp_geo
Create Date: 2026-02-27

"""

from alembic import op
import sqlalchemy as sa

revision = "20260227_pist_asigna"
down_revision = "20260227_transp_geo"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "logisticas",
        sa.Column(
            "pistoleado_asigna",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Si True, al pistolear asigna la logística en vez de verificar coincidencia",
        ),
    )


def downgrade():
    op.drop_column("logisticas", "pistoleado_asigna")
