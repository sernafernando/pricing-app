"""add structured address fields + lat/lng to rrhh_empleados

Revision ID: 20260316c1
Revises: 20260316b1
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa

revision = "20260316c1"
down_revision = "20260316b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rrhh_empleados", sa.Column("calle", sa.String(200), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("numero", sa.String(20), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("piso_depto", sa.String(50), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("entre_calles", sa.String(200), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("localidad", sa.String(100), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("provincia", sa.String(100), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("codigo_postal", sa.String(20), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("latitud", sa.Numeric(10, 8), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("longitud", sa.Numeric(11, 8), nullable=True))


def downgrade() -> None:
    op.drop_column("rrhh_empleados", "longitud")
    op.drop_column("rrhh_empleados", "latitud")
    op.drop_column("rrhh_empleados", "codigo_postal")
    op.drop_column("rrhh_empleados", "provincia")
    op.drop_column("rrhh_empleados", "localidad")
    op.drop_column("rrhh_empleados", "entre_calles")
    op.drop_column("rrhh_empleados", "piso_depto")
    op.drop_column("rrhh_empleados", "numero")
    op.drop_column("rrhh_empleados", "calle")
