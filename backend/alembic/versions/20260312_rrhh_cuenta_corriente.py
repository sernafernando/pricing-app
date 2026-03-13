"""Add RRHH cuenta corriente + herramientas tables

Creates 3 tables:
- rrhh_asignacion_herramienta: tools/equipment assigned to employees
- rrhh_cuenta_corriente: per-employee ledger header with running balance
- rrhh_cuenta_corriente_movimiento: individual debit/credit entries

Revision ID: 20260312_rrhh_cuenta_corriente
Revises: 20260312_rrhh_vacaciones
Create Date: 2026-03-12

"""

from alembic import op
import sqlalchemy as sa

revision = "20260312_rrhh_cuenta_corriente"
down_revision = "20260312_rrhh_vacaciones"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. rrhh_asignacion_herramienta ──────────────────────────
    op.create_table(
        "rrhh_asignacion_herramienta",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "empleado_id",
            sa.Integer,
            sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("descripcion", sa.String(255), nullable=False),
        sa.Column("codigo_inventario", sa.String(100), nullable=True),
        sa.Column("item_id", sa.Integer, nullable=True),
        sa.Column("cantidad", sa.Integer, nullable=False, server_default="1"),
        sa.Column("fecha_asignacion", sa.Date, nullable=False),
        sa.Column("fecha_devolucion", sa.Date, nullable=True),
        sa.Column(
            "estado",
            sa.String(30),
            nullable=False,
            server_default="asignado",
        ),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column(
            "asignado_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_herramientas_empleado_estado",
        "rrhh_asignacion_herramienta",
        ["empleado_id", "estado"],
    )

    # ── 2. rrhh_cuenta_corriente ────────────────────────────────
    op.create_table(
        "rrhh_cuenta_corriente",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "empleado_id",
            sa.Integer,
            sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column(
            "saldo",
            sa.Numeric(15, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── 3. rrhh_cuenta_corriente_movimiento ─────────────────────
    op.create_table(
        "rrhh_cuenta_corriente_movimiento",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "cuenta_id",
            sa.Integer,
            sa.ForeignKey("rrhh_cuenta_corriente.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "empleado_id",
            sa.Integer,
            sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("monto", sa.Numeric(15, 2), nullable=False),
        sa.Column("fecha", sa.Date, nullable=False, index=True),
        sa.Column("concepto", sa.String(255), nullable=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("item_id", sa.Integer, nullable=True),
        sa.Column("ct_transaction", sa.Integer, nullable=True),
        sa.Column("cuota_numero", sa.Integer, nullable=True),
        sa.Column("cuota_total", sa.Integer, nullable=True),
        sa.Column("saldo_posterior", sa.Numeric(15, 2), nullable=False),
        sa.Column(
            "registrado_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_cc_mov_empleado_fecha",
        "rrhh_cuenta_corriente_movimiento",
        ["empleado_id", "fecha"],
    )
    op.create_index(
        "idx_cc_mov_cuenta_fecha",
        "rrhh_cuenta_corriente_movimiento",
        ["cuenta_id", "fecha"],
    )


def downgrade():
    op.drop_index(
        "idx_cc_mov_cuenta_fecha",
        table_name="rrhh_cuenta_corriente_movimiento",
    )
    op.drop_index(
        "idx_cc_mov_empleado_fecha",
        table_name="rrhh_cuenta_corriente_movimiento",
    )
    op.drop_table("rrhh_cuenta_corriente_movimiento")
    op.drop_table("rrhh_cuenta_corriente")
    op.drop_index(
        "idx_herramientas_empleado_estado",
        table_name="rrhh_asignacion_herramienta",
    )
    op.drop_table("rrhh_asignacion_herramienta")
