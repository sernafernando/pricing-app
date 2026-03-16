"""create rrhh_empleado_horarios table

Revision ID: fa4b31d7998e
Revises: 20260313_retornado
Create Date: 2026-03-16 10:33:42.366227

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa4b31d7998e'
down_revision: Union[str, None] = '20260313_retornado'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rrhh_empleado_horarios",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "empleado_id",
            sa.Integer(),
            sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "horario_config_id",
            sa.Integer(),
            sa.ForeignKey("rrhh_horarios_config.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prioridad", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("empleado_id", "horario_config_id", name="uq_empleado_horario"),
    )
    op.create_index("ix_rrhh_empleado_horarios_empleado_id", "rrhh_empleado_horarios", ["empleado_id"])
    op.create_index("ix_rrhh_empleado_horarios_horario_config_id", "rrhh_empleado_horarios", ["horario_config_id"])


def downgrade() -> None:
    op.drop_index("ix_rrhh_empleado_horarios_horario_config_id", table_name="rrhh_empleado_horarios")
    op.drop_index("ix_rrhh_empleado_horarios_empleado_id", table_name="rrhh_empleado_horarios")
    op.drop_table("rrhh_empleado_horarios")
