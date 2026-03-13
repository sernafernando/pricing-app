"""Add RRHH vacaciones tables

Creates 2 tables:
- rrhh_vacaciones_periodo: annual vacation periods per employee (Ley 20.744 art 150)
- rrhh_vacaciones_solicitud: vacation requests against a period

Revision ID: 20260312_rrhh_vacaciones
Revises: 20260312_rrhh_sanciones
Create Date: 2026-03-12

"""

from alembic import op
import sqlalchemy as sa

revision = "20260312_rrhh_vacaciones"
down_revision = "20260312_rrhh_sanciones"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. rrhh_vacaciones_periodo ───────────────────────────────
    op.create_table(
        "rrhh_vacaciones_periodo",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "empleado_id",
            sa.Integer,
            sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("anio", sa.Integer, nullable=False),
        sa.Column("dias_correspondientes", sa.Integer, nullable=False),
        sa.Column("dias_gozados", sa.Integer, nullable=False, server_default="0"),
        sa.Column("dias_pendientes", sa.Integer, nullable=False),
        sa.Column("antiguedad_anios", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("empleado_id", "anio", name="uq_vacaciones_periodo_empleado_anio"),
    )

    # ── 2. rrhh_vacaciones_solicitud ─────────────────────────────
    op.create_table(
        "rrhh_vacaciones_solicitud",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "empleado_id",
            sa.Integer,
            sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "periodo_id",
            sa.Integer,
            sa.ForeignKey("rrhh_vacaciones_periodo.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("fecha_desde", sa.Date, nullable=False),
        sa.Column("fecha_hasta", sa.Date, nullable=False),
        sa.Column("dias_solicitados", sa.Integer, nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente", index=True),
        sa.Column("motivo_rechazo", sa.Text, nullable=True),
        # Approval
        sa.Column("aprobada_por_id", sa.Integer, sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("aprobada_at", sa.DateTime(timezone=True), nullable=True),
        # Audit
        sa.Column("solicitada_por_id", sa.Integer, sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "idx_vacaciones_solicitud_estado",
        "rrhh_vacaciones_solicitud",
        ["empleado_id", "estado"],
    )


def downgrade():
    op.drop_index("idx_vacaciones_solicitud_estado", table_name="rrhh_vacaciones_solicitud")
    op.drop_table("rrhh_vacaciones_solicitud")
    op.drop_table("rrhh_vacaciones_periodo")
