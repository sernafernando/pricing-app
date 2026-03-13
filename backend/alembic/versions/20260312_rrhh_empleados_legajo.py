"""Create RRHH empleados, schema legajo, tipo documento, documentos and legajo historial tables

Revision ID: 20260312_rrhh_empleados
Revises: 20260312_fs_fix_log
Create Date: 2026-03-12

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260312_rrhh_empleados"
down_revision = "20260312_fs_fix_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- rrhh_schema_legajo ---
    op.create_table(
        "rrhh_schema_legajo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("tipo_campo", sa.String(length=50), nullable=False),
        sa.Column("requerido", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "opciones", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre"),
    )
    op.create_index(
        op.f("ix_rrhh_schema_legajo_id"), "rrhh_schema_legajo", ["id"], unique=False
    )

    # --- rrhh_tipo_documento ---
    op.create_table(
        "rrhh_tipo_documento",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("descripcion", sa.String(length=500), nullable=True),
        sa.Column(
            "requiere_vencimiento",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre"),
    )
    op.create_index(
        op.f("ix_rrhh_tipo_documento_id"), "rrhh_tipo_documento", ["id"], unique=False
    )

    # --- rrhh_empleados ---
    op.create_table(
        "rrhh_empleados",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("apellido", sa.String(length=100), nullable=False),
        sa.Column("dni", sa.String(length=20), nullable=False),
        sa.Column("cuil", sa.String(length=20), nullable=True),
        sa.Column("fecha_nacimiento", sa.Date(), nullable=True),
        sa.Column("domicilio", sa.String(length=500), nullable=True),
        sa.Column("telefono", sa.String(length=50), nullable=True),
        sa.Column("email_personal", sa.String(length=255), nullable=True),
        sa.Column("contacto_emergencia", sa.String(length=255), nullable=True),
        sa.Column("contacto_emergencia_tel", sa.String(length=50), nullable=True),
        sa.Column("legajo", sa.String(length=20), nullable=False),
        sa.Column("fecha_ingreso", sa.Date(), nullable=False),
        sa.Column("fecha_egreso", sa.Date(), nullable=True),
        sa.Column("puesto", sa.String(length=100), nullable=True),
        sa.Column("area", sa.String(length=100), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="activo"),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("foto_path", sa.String(length=500), nullable=True),
        sa.Column(
            "datos_custom", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("creado_por_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["creado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rrhh_empleados_id"), "rrhh_empleados", ["id"], unique=False)
    op.create_index(op.f("ix_rrhh_empleados_dni"), "rrhh_empleados", ["dni"], unique=True)
    op.create_index(
        op.f("ix_rrhh_empleados_legajo"), "rrhh_empleados", ["legajo"], unique=True
    )
    op.create_index(
        op.f("ix_rrhh_empleados_cuil"), "rrhh_empleados", ["cuil"], unique=False
    )
    op.create_index(
        op.f("ix_rrhh_empleados_estado"), "rrhh_empleados", ["estado"], unique=False
    )
    op.create_index(
        op.f("ix_rrhh_empleados_activo"), "rrhh_empleados", ["activo"], unique=False
    )
    op.create_index(
        op.f("ix_rrhh_empleados_usuario_id"),
        "rrhh_empleados",
        ["usuario_id"],
        unique=True,
    )
    op.create_index(
        "idx_rrhh_empleados_nombre_apellido",
        "rrhh_empleados",
        ["nombre", "apellido"],
        unique=False,
    )
    op.create_index(
        "idx_rrhh_empleados_estado_activo",
        "rrhh_empleados",
        ["estado", "activo"],
        unique=False,
    )

    # --- rrhh_documentos ---
    op.create_table(
        "rrhh_documentos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empleado_id", sa.Integer(), nullable=False),
        sa.Column("tipo_documento_id", sa.Integer(), nullable=False),
        sa.Column("nombre_archivo", sa.String(length=255), nullable=False),
        sa.Column("path_archivo", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("tamano_bytes", sa.Integer(), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("fecha_vencimiento", sa.Date(), nullable=True),
        sa.Column("numero_documento", sa.String(length=100), nullable=True),
        sa.Column("subido_por_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["empleado_id"], ["rrhh_empleados.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tipo_documento_id"], ["rrhh_tipo_documento.id"]),
        sa.ForeignKeyConstraint(["subido_por_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_rrhh_documentos_id"), "rrhh_documentos", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_rrhh_documentos_empleado_id"),
        "rrhh_documentos",
        ["empleado_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rrhh_documentos_tipo_documento_id"),
        "rrhh_documentos",
        ["tipo_documento_id"],
        unique=False,
    )
    op.create_index(
        "idx_rrhh_docs_empleado_tipo",
        "rrhh_documentos",
        ["empleado_id", "tipo_documento_id"],
        unique=False,
    )

    # --- rrhh_legajo_historial ---
    op.create_table(
        "rrhh_legajo_historial",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empleado_id", sa.Integer(), nullable=False),
        sa.Column("campo", sa.String(length=100), nullable=False),
        sa.Column("valor_anterior", sa.Text(), nullable=True),
        sa.Column("valor_nuevo", sa.Text(), nullable=True),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["empleado_id"], ["rrhh_empleados.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_rrhh_legajo_historial_id"),
        "rrhh_legajo_historial",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rrhh_legajo_historial_empleado_id"),
        "rrhh_legajo_historial",
        ["empleado_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rrhh_legajo_historial_usuario_id"),
        "rrhh_legajo_historial",
        ["usuario_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("rrhh_legajo_historial")
    op.drop_table("rrhh_documentos")
    op.drop_table("rrhh_empleados")
    op.drop_table("rrhh_tipo_documento")
    op.drop_table("rrhh_schema_legajo")
