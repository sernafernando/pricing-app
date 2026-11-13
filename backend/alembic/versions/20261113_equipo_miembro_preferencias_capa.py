"""Add each member's own color layer preferences to equipo_miembro

Columns (Publicaciones ML's layer selector, pubml-capa-default S2-S4):
- por_defecto: the layer Publicaciones ML opens on for this user (at most one per user; none = the global layer).
- mostrar_referencia_global: whether the global color reference shows on this team's layer (default: shown).

A partial unique index keeps at most one default per user.

Existing rows keep today's behavior: no default (global) and the reference shown.

Revision ID: 20261113_equipo_miembro_preferencias_capa
Revises: 20261113_permiso_mejores_ofertas_pms
Create Date: 2026-11-13

"""

import sqlalchemy as sa
from alembic import op

revision = "20261113_equipo_miembro_preferencias_capa"
down_revision = "20261113_permiso_mejores_ofertas_pms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "equipo_miembro",
        sa.Column("por_defecto", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "equipo_miembro",
        sa.Column("mostrar_referencia_global", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index(
        "uq_equipo_miembro_usuario_por_defecto",
        "equipo_miembro",
        ["usuario_id"],
        unique=True,
        postgresql_where=sa.text("por_defecto"),
    )


def downgrade() -> None:
    op.drop_index("uq_equipo_miembro_usuario_por_defecto", table_name="equipo_miembro")
    op.drop_column("equipo_miembro", "mostrar_referencia_global")
    op.drop_column("equipo_miembro", "por_defecto")
