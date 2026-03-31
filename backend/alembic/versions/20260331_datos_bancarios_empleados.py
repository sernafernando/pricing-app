"""Add datos bancarios columns to rrhh_empleados

Campos de cuenta sueldo: banco, CBU, alias, tipo cuenta, nro cuenta.
Un empleado tiene una sola cuenta sueldo (titular = empleado).

Revision ID: 20260331_datos_bancarios
Revises: 20260330_rol_fichaje
Create Date: 2026-03-31
"""

import sqlalchemy as sa
from alembic import op

revision = "20260331_datos_bancarios"
down_revision = "20260330_rol_fichaje"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rrhh_empleados", sa.Column("banco_nombre", sa.String(100), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("banco_cbu", sa.String(22), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("banco_alias", sa.String(100), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("banco_tipo_cuenta", sa.String(20), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("banco_nro_cuenta", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("rrhh_empleados", "banco_nro_cuenta")
    op.drop_column("rrhh_empleados", "banco_tipo_cuenta")
    op.drop_column("rrhh_empleados", "banco_alias")
    op.drop_column("rrhh_empleados", "banco_cbu")
    op.drop_column("rrhh_empleados", "banco_nombre")
