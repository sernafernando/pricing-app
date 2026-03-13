"""Make rrhh_fichadas.empleado_id nullable + add hikvision_employee_no

Allows storing Hikvision events even when the device user hasn't been
mapped to an employee yet. The hikvision_employee_no field stores the
original employeeNoString for retroactive matching on map.

Revision ID: 20260313_rrhh_fichadas_nullable_empleado
Revises: 20260313_rrhh_hikvision_mapping
Create Date: 2026-03-13

"""

from alembic import op
import sqlalchemy as sa

revision = "20260313_rrhh_fichadas_null_emp"
down_revision = "20260313_rrhh_hikvision_mapping"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Make empleado_id nullable
    op.alter_column(
        "rrhh_fichadas",
        "empleado_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # 2. Add hikvision_employee_no column
    op.add_column(
        "rrhh_fichadas",
        sa.Column("hikvision_employee_no", sa.String(20), nullable=True),
    )
    op.create_index(
        "idx_rrhh_fichadas_hik_emp_no",
        "rrhh_fichadas",
        ["hikvision_employee_no"],
    )


def downgrade():
    op.drop_index("idx_rrhh_fichadas_hik_emp_no", table_name="rrhh_fichadas")
    op.drop_column("rrhh_fichadas", "hikvision_employee_no")
    # NOTE: downgrade doesn't restore NOT NULL on empleado_id
    # because existing rows may have NULLs.
