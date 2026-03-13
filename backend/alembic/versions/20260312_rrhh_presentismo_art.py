"""Add RRHH presentismo + ART tables

Creates 3 tables:
- rrhh_presentismo_diario: daily attendance per employee
- rrhh_art_casos: workplace accident cases
- rrhh_art_documentos: medical documents for ART cases

Revision ID: 20260312_rrhh_presentismo_art
Revises: 20260312_rrhh_permisos
Create Date: 2026-03-12

"""

from alembic import op
import sqlalchemy as sa

revision = "20260312_rrhh_presentismo_art"
down_revision = "20260312_rrhh_permisos"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. rrhh_art_casos (must exist before presentismo FK) ─────
    op.create_table(
        "rrhh_art_casos",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "empleado_id",
            sa.Integer,
            sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Siniestro
        sa.Column("numero_siniestro", sa.String(50), nullable=True, index=True),
        sa.Column("fecha_accidente", sa.Date, nullable=False),
        sa.Column("descripcion_accidente", sa.Text, nullable=True),
        sa.Column("lugar_accidente", sa.String(255), nullable=True),
        sa.Column("tipo_lesion", sa.String(100), nullable=True),
        sa.Column("parte_cuerpo", sa.String(100), nullable=True),
        # ART (aseguradora)
        sa.Column("art_nombre", sa.String(200), nullable=True),
        sa.Column("numero_expediente_art", sa.String(50), nullable=True),
        # Evolución
        sa.Column("estado", sa.String(30), nullable=False, server_default="abierto", index=True),
        sa.Column("fecha_alta_medica", sa.Date, nullable=True),
        sa.Column("dias_baja", sa.Integer, nullable=True),
        sa.Column("porcentaje_incapacidad", sa.Numeric(5, 2), nullable=True),
        # Costo
        sa.Column("monto_indemnizacion", sa.Numeric(15, 2), nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        # Audit
        sa.Column(
            "creado_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── 2. rrhh_art_documentos ───────────────────────────────────
    op.create_table(
        "rrhh_art_documentos",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "art_caso_id",
            sa.Integer,
            sa.ForeignKey("rrhh_art_casos.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("nombre_archivo", sa.String(255), nullable=False),
        sa.Column("path_archivo", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("tamano_bytes", sa.Integer, nullable=True),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column(
            "subido_por_id",
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

    # ── 3. rrhh_presentismo_diario ───────────────────────────────
    op.create_table(
        "rrhh_presentismo_diario",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "empleado_id",
            sa.Integer,
            sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("fecha", sa.Date, nullable=False, index=True),
        sa.Column("estado", sa.String(30), nullable=False, server_default="presente"),
        sa.Column("hora_ingreso", sa.Time, nullable=True),
        sa.Column("hora_egreso", sa.Time, nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column(
            "art_caso_id",
            sa.Integer,
            sa.ForeignKey("rrhh_art_casos.id"),
            nullable=True,
        ),
        sa.Column(
            "registrado_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # Constraints
        sa.UniqueConstraint("empleado_id", "fecha", name="uq_presentismo_empleado_fecha"),
    )

    # Composite index for grid queries
    op.create_index(
        "idx_presentismo_fecha_estado",
        "rrhh_presentismo_diario",
        ["fecha", "estado"],
    )


def downgrade():
    op.drop_index("idx_presentismo_fecha_estado", table_name="rrhh_presentismo_diario")
    op.drop_table("rrhh_presentismo_diario")
    op.drop_table("rrhh_art_documentos")
    op.drop_table("rrhh_art_casos")
