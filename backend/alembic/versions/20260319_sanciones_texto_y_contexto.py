"""Add texto_sancion to sanciones and texto_predeterminado to tipo_sancion

Revision ID: a3f5c8d91e02
Revises: df027d1b05df
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa

revision = "a3f5c8d91e02"
down_revision = "df027d1b05df"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "rrhh_sanciones", sa.Column("texto_sancion", sa.Text(), nullable=True)
    )
    op.add_column(
        "rrhh_tipo_sancion",
        sa.Column("texto_predeterminado", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("rrhh_tipo_sancion", "texto_predeterminado")
    op.drop_column("rrhh_sanciones", "texto_sancion")
