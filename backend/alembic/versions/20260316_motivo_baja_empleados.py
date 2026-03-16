"""create rrhh_motivo_baja + add baja fields to rrhh_empleados

Revision ID: 20260316b1
Revises: 20260316a1
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa

revision = "20260316b1"
down_revision = "20260316a1"
branch_labels = None
depends_on = None

MOTIVOS_SEED = [
    {"nombre": "Renuncia", "descripcion": "Renuncia voluntaria del empleado", "requiere_documentacion": True, "orden": 1},
    {"nombre": "Despido con causa", "descripcion": "Despido por causa justificada", "requiere_documentacion": True, "orden": 2},
    {"nombre": "Despido sin causa", "descripcion": "Despido sin causa justificada", "requiere_documentacion": True, "orden": 3},
    {"nombre": "Mutuo acuerdo", "descripcion": "Desvinculación por mutuo acuerdo", "requiere_documentacion": True, "orden": 4},
    {"nombre": "Jubilación", "descripcion": "Baja por jubilación del empleado", "requiere_documentacion": True, "orden": 5},
    {"nombre": "Fallecimiento", "descripcion": "Baja por fallecimiento", "requiere_documentacion": True, "orden": 6},
    {"nombre": "Fin de contrato", "descripcion": "Finalización de contrato a plazo fijo", "requiere_documentacion": False, "orden": 7},
    {"nombre": "Periodo de prueba", "descripcion": "No superó el periodo de prueba", "requiere_documentacion": False, "orden": 8},
    {"nombre": "Abandono de trabajo", "descripcion": "Abandono de puesto de trabajo", "requiere_documentacion": True, "orden": 9},
]


def upgrade() -> None:
    # 1. Create motivo_baja table
    op.create_table(
        "rrhh_motivo_baja",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("nombre", sa.String(100), unique=True, nullable=False),
        sa.Column("descripcion", sa.String(500), nullable=True),
        sa.Column("requiere_documentacion", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 2. Seed initial motivos
    motivo_table = sa.table(
        "rrhh_motivo_baja",
        sa.column("nombre", sa.String),
        sa.column("descripcion", sa.String),
        sa.column("requiere_documentacion", sa.Boolean),
        sa.column("orden", sa.Integer),
    )
    op.bulk_insert(motivo_table, MOTIVOS_SEED)

    # 3. Add baja fields to empleados
    op.add_column("rrhh_empleados", sa.Column("motivo_baja_id", sa.Integer(), nullable=True))
    op.add_column("rrhh_empleados", sa.Column("detalle_baja", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_empleados_motivo_baja",
        "rrhh_empleados",
        "rrhh_motivo_baja",
        ["motivo_baja_id"],
        ["id"],
    )
    op.create_index("idx_empleados_motivo_baja", "rrhh_empleados", ["motivo_baja_id"])


def downgrade() -> None:
    op.drop_index("idx_empleados_motivo_baja", "rrhh_empleados")
    op.drop_constraint("fk_empleados_motivo_baja", "rrhh_empleados", type_="foreignkey")
    op.drop_column("rrhh_empleados", "detalle_baja")
    op.drop_column("rrhh_empleados", "motivo_baja_id")
    op.drop_table("rrhh_motivo_baja")
