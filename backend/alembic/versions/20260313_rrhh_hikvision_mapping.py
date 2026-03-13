"""Add hikvision_employee_no to rrhh_empleados

Maps each employee to their Hikvision device employeeNo for fichada sync.
Field is nullable (not all employees have Hikvision access) and unique.

Revision ID: 20260313_rrhh_hikvision_mapping
Revises: 20260312_rrhh_horarios_fichadas
Create Date: 2026-03-13

"""

from alembic import op
import sqlalchemy as sa

revision = "20260313_rrhh_hikvision_mapping"
down_revision = "20260312_rrhh_horarios_fichadas"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "rrhh_empleados",
        sa.Column("hikvision_employee_no", sa.String(20), nullable=True),
    )
    op.create_index(
        "idx_rrhh_empleados_hikvision_no",
        "rrhh_empleados",
        ["hikvision_employee_no"],
        unique=True,
    )


def downgrade():
    op.drop_index("idx_rrhh_empleados_hikvision_no", table_name="rrhh_empleados")
    op.drop_column("rrhh_empleados", "hikvision_employee_no")
