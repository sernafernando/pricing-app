"""Agregar columna oculta a subcategorias_grupos

Banlist para ocultar subcategorías que no son productos reales
(ej: "Cargar Subrubro / SubCategoria", "Envios") del panel de
asignación de grupos de comisión.

Revision ID: 20260218_oculta_subcats
Revises: 20260218_permisos_flex
Create Date: 2026-02-18

"""

from alembic import op
import sqlalchemy as sa

revision = "20260218_oculta_subcats"
down_revision = "20260218_permisos_flex"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "subcategorias_grupos",
        sa.Column("oculta", sa.Boolean(), server_default=sa.text("false"), nullable=True),
    )


def downgrade():
    op.drop_column("subcategorias_grupos", "oculta")
