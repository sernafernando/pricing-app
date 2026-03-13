"""Add RRHH sanciones tables

Creates 2 tables:
- rrhh_tipo_sancion: configurable sanction types
- rrhh_sanciones: sanctions applied to employees

Revision ID: 20260312_rrhh_sanciones
Revises: 20260312_rrhh_presentismo_art
Create Date: 2026-03-12

"""

from alembic import op
import sqlalchemy as sa

revision = "20260312_rrhh_sanciones"
down_revision = "20260312_rrhh_presentismo_art"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. rrhh_tipo_sancion ─────────────────────────────────────
    op.create_table(
        "rrhh_tipo_sancion",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("nombre", sa.String(100), unique=True, nullable=False),
        sa.Column("descripcion", sa.String(500), nullable=True),
        sa.Column("dias_suspension", sa.Integer, nullable=True),
        sa.Column("requiere_descuento", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("activo", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("orden", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── 2. rrhh_sanciones ────────────────────────────────────────
    op.create_table(
        "rrhh_sanciones",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "empleado_id",
            sa.Integer,
            sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "tipo_sancion_id",
            sa.Integer,
            sa.ForeignKey("rrhh_tipo_sancion.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("fecha", sa.Date, nullable=False, index=True),
        sa.Column("motivo", sa.Text, nullable=False),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("fecha_desde", sa.Date, nullable=True),
        sa.Column("fecha_hasta", sa.Date, nullable=True),
        # Anulación
        sa.Column("anulada", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("anulada_motivo", sa.Text, nullable=True),
        sa.Column("anulada_por_id", sa.Integer, sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("anulada_at", sa.DateTime(timezone=True), nullable=True),
        # Audit
        sa.Column("aplicada_por_id", sa.Integer, sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index(
        "idx_sanciones_empleado_fecha",
        "rrhh_sanciones",
        ["empleado_id", "fecha"],
    )

    # Seed default sanction types
    op.execute("""
        INSERT INTO rrhh_tipo_sancion (nombre, descripcion, dias_suspension, requiere_descuento, orden)
        VALUES
            ('Apercibimiento verbal', 'Llamado de atención verbal documentado', NULL, false, 1),
            ('Apercibimiento escrito', 'Llamado de atención por escrito', NULL, false, 2),
            ('Suspensión 1 día', 'Suspensión disciplinaria de 1 día', 1, true, 3),
            ('Suspensión 3 días', 'Suspensión disciplinaria de 3 días', 3, true, 4),
            ('Suspensión 5 días', 'Suspensión disciplinaria de 5 días', 5, true, 5)
        ON CONFLICT (nombre) DO NOTHING;
    """)


def downgrade():
    op.drop_index("idx_sanciones_empleado_fecha", table_name="rrhh_sanciones")
    op.drop_table("rrhh_sanciones")
    op.drop_table("rrhh_tipo_sancion")
