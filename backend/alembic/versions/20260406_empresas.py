"""Add empresas table and empresa_id FK to rrhh_empleados

Empresas propias del grupo (Pastoriza, Grupo Gauss, etc.).
Cada empleado se asigna a una empresa para diferenciar sueldos,
cuentas bancarias y datos fiscales.

Revision ID: 20260406_empresas
Revises: 20260406_motivo_aus
Create Date: 2026-04-06
"""

import sqlalchemy as sa
from alembic import op

revision = "20260406_empresas"
down_revision = "20260406_motivo_aus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Crear tabla empresas
    op.create_table(
        "empresas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("razon_social", sa.String(255), nullable=True),
        sa.Column("cuit", sa.String(20), nullable=True),
        sa.Column("direccion", sa.String(500), nullable=True),
        sa.Column("telefono", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre"),
        sa.UniqueConstraint("cuit"),
    )
    op.create_index(op.f("ix_empresas_id"), "empresas", ["id"])

    # 2. Agregar FK a rrhh_empleados
    op.add_column(
        "rrhh_empleados",
        sa.Column("empresa_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_empleado_empresa",
        "rrhh_empleados",
        "empresas",
        ["empresa_id"],
        ["id"],
    )
    op.create_index("ix_rrhh_empleados_empresa_id", "rrhh_empleados", ["empresa_id"])

    # 3. Seed empresas iniciales
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO empresas (nombre, orden) VALUES
            ('Pastoriza', 1),
            ('Grupo Gauss', 2)
            ON CONFLICT (nombre) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_rrhh_empleados_empresa_id", table_name="rrhh_empleados")
    op.drop_constraint("fk_empleado_empresa", "rrhh_empleados", type_="foreignkey")
    op.drop_column("rrhh_empleados", "empresa_id")
    op.drop_index(op.f("ix_empresas_id"), table_name="empresas")
    op.drop_table("empresas")
