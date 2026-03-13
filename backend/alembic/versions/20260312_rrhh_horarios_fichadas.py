"""Add RRHH horarios + fichadas tables

Creates 3 tables:
- rrhh_fichadas: clock-in/out records from Hikvision or manual entry
- rrhh_horarios_config: shift schedule definitions
- rrhh_horarios_excepciones: holidays and special days

Seeds 3 default schedules: Turno Mañana (8-17), Turno Tarde (9-18), Part-time (9-13)

Revision ID: 20260312_rrhh_horarios_fichadas
Revises: 20260312_rrhh_cuenta_corriente
Create Date: 2026-03-12

"""

from alembic import op
import sqlalchemy as sa

revision = "20260312_rrhh_horarios_fichadas"
down_revision = "20260312_rrhh_cuenta_corriente"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. rrhh_fichadas ────────────────────────────────────────
    op.create_table(
        "rrhh_fichadas",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "empleado_id",
            sa.Integer,
            sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), nullable=False, index=True
        ),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column(
            "origen",
            sa.String(20),
            nullable=False,
            server_default="hikvision",
        ),
        sa.Column("device_serial", sa.String(100), nullable=True),
        sa.Column(
            "event_id",
            sa.String(100),
            nullable=True,
            unique=True,
            index=True,
        ),
        sa.Column(
            "registrado_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column("motivo_manual", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_fichadas_empleado_timestamp",
        "rrhh_fichadas",
        ["empleado_id", "timestamp"],
    )

    # ── 2. rrhh_horarios_config ─────────────────────────────────
    op.create_table(
        "rrhh_horarios_config",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("nombre", sa.String(100), unique=True, nullable=False),
        sa.Column("hora_entrada", sa.Time, nullable=False),
        sa.Column("hora_salida", sa.Time, nullable=False),
        sa.Column(
            "tolerancia_minutos",
            sa.Integer,
            nullable=False,
            server_default="15",
        ),
        sa.Column(
            "dias_semana",
            sa.String(20),
            nullable=False,
            server_default="1,2,3,4,5",
        ),
        sa.Column(
            "activo",
            sa.Boolean,
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # Seed 3 default schedules
    op.execute("""
        INSERT INTO rrhh_horarios_config (nombre, hora_entrada, hora_salida, tolerancia_minutos, dias_semana)
        VALUES
            ('Turno Mañana 8-17', '08:00', '17:00', 15, '1,2,3,4,5'),
            ('Turno Tarde 9-18', '09:00', '18:00', 15, '1,2,3,4,5'),
            ('Part-time 9-13', '09:00', '13:00', 10, '1,2,3,4,5')
        ON CONFLICT (nombre) DO NOTHING
    """)

    # ── 3. rrhh_horarios_excepciones ────────────────────────────
    op.create_table(
        "rrhh_horarios_excepciones",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "fecha", sa.Date, nullable=False, unique=True, index=True
        ),
        sa.Column("tipo", sa.String(30), nullable=False),
        sa.Column("descripcion", sa.String(255), nullable=False),
        sa.Column(
            "es_laborable",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade():
    op.drop_table("rrhh_horarios_excepciones")
    op.drop_table("rrhh_horarios_config")
    op.drop_index(
        "idx_fichadas_empleado_timestamp", table_name="rrhh_fichadas"
    )
    op.drop_table("rrhh_fichadas")
