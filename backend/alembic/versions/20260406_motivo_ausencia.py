"""Add rrhh_motivo_ausencia table and motivo_ausencia_id to presentismo

Motivos de ausencia configurables para el módulo de presentismo.
Cuando un empleado se marca como "ausente", se puede asociar un motivo
(enfermedad, trámite, sin aviso, etc.) + observaciones.

Revision ID: 20260406_motivo_aus
Revises: 20260401_mlsubstatus
Create Date: 2026-04-06
"""

import sqlalchemy as sa
from alembic import op

revision = "20260406_motivo_aus"
down_revision = "20260401_mlsubstatus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Crear tabla rrhh_motivo_ausencia
    op.create_table(
        "rrhh_motivo_ausencia",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("descripcion", sa.String(500), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre"),
    )
    op.create_index(op.f("ix_rrhh_motivo_ausencia_id"), "rrhh_motivo_ausencia", ["id"])

    # 2. Agregar FK a rrhh_presentismo_diario
    op.add_column(
        "rrhh_presentismo_diario",
        sa.Column("motivo_ausencia_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_presentismo_motivo_ausencia",
        "rrhh_presentismo_diario",
        "rrhh_motivo_ausencia",
        ["motivo_ausencia_id"],
        ["id"],
    )

    # 3. Seed motivos comunes
    motivos = op.get_bind()
    motivos.execute(
        sa.text(
            """
            INSERT INTO rrhh_motivo_ausencia (nombre, descripcion, orden) VALUES
            ('Enfermedad', 'Ausencia por enfermedad del empleado', 1),
            ('Familiar enfermo', 'Ausencia por enfermedad de familiar directo', 2),
            ('Trámite personal', 'Trámite bancario, judicial, médico, etc.', 3),
            ('Estudio / Examen', 'Día de examen o jornada de estudio', 4),
            ('Mudanza', 'Día de mudanza', 5),
            ('Fallecimiento familiar', 'Licencia por duelo', 6),
            ('Sin aviso', 'El empleado no se presentó ni avisó', 7),
            ('Otro', 'Motivo no categorizado', 99)
            ON CONFLICT (nombre) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_presentismo_motivo_ausencia",
        "rrhh_presentismo_diario",
        type_="foreignkey",
    )
    op.drop_column("rrhh_presentismo_diario", "motivo_ausencia_id")
    op.drop_index(op.f("ix_rrhh_motivo_ausencia_id"), table_name="rrhh_motivo_ausencia")
    op.drop_table("rrhh_motivo_ausencia")
