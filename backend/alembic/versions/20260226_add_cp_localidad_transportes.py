"""Agregar cp y localidad a transportes

Revision ID: 20260226_transp_loc
Revises: 20260226_transp_fk
Create Date: 2026-02-26

"""

from alembic import op
import sqlalchemy as sa

revision = "20260226_transp_loc"
down_revision = "20260226_transp_fk"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("transportes", sa.Column("cp", sa.String(10), nullable=True))
    op.add_column("transportes", sa.Column("localidad", sa.String(200), nullable=True))


def downgrade():
    op.drop_column("transportes", "localidad")
    op.drop_column("transportes", "cp")
