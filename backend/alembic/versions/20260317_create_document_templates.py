"""Create document_templates table and seed documentos permissions

Revision ID: 20260317_doc_templates
Revises: 20260316t1
Create Date: 2026-03-17

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260317_doc_templates"
down_revision = "20260316t1"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "documentos.disenar",
        "Diseñar templates de documentos",
        "Acceso al Designer visual de templates PDF: crear, editar y eliminar templates",
        "documentos",
        140,
        True,
    ),
    (
        "documentos.imprimir",
        "Generar documentos PDF",
        "Generar documentos PDF desde cualquier módulo usando templates existentes",
        "documentos",
        141,
        False,
    ),
]

# Roles that get document permissions
ROL_PERMISOS = {
    "ADMIN": ["documentos.disenar", "documentos.imprimir"],
    "GERENTE": ["documentos.imprimir"],
    "VENTAS": ["documentos.imprimir"],
}


def upgrade():
    # 1. Create document_templates table
    op.create_table(
        "document_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("contexto", sa.String(length=50), nullable=False),
        sa.Column("template_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("creado_por_id", sa.Integer(), nullable=False),
        sa.Column("actualizado_por_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["creado_por_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["actualizado_por_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_templates_id"), "document_templates", ["id"], unique=False)
    op.create_index(op.f("ix_document_templates_contexto"), "document_templates", ["contexto"], unique=False)
    op.create_index(op.f("ix_document_templates_activo"), "document_templates", ["activo"], unique=False)

    # 2. Insert permissions into catalog
    for codigo, nombre, desc, cat, orden, critico in PERMISOS:
        critico_str = "true" if critico else "false"
        op.execute(
            f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES
                ('{codigo}', '{nombre}', '{desc}', '{cat}', {orden}, {critico_str}, NOW())
            ON CONFLICT (codigo) DO NOTHING;
        """
        )

    # 3. Assign to roles
    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            op.execute(
                f"""
                INSERT INTO roles_permisos_base (rol_id, permiso_id)
                SELECT r.id, p.id
                FROM roles r
                CROSS JOIN permisos p
                WHERE r.codigo = '{rol}'
                  AND p.codigo = '{codigo}'
                ON CONFLICT DO NOTHING;
            """
            )


def downgrade():
    codigos = [p[0] for p in PERMISOS]
    codigos_str = ", ".join(f"'{c}'" for c in codigos)

    # Remove role assignments
    op.execute(
        f"""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo IN ({codigos_str})
        );
    """
    )

    # Remove user overrides
    op.execute(
        f"""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo IN ({codigos_str})
        );
    """
    )

    # Remove permissions
    op.execute(
        f"""
        DELETE FROM permisos WHERE codigo IN ({codigos_str});
    """
    )

    # Drop table
    op.drop_index(op.f("ix_document_templates_activo"), table_name="document_templates")
    op.drop_index(op.f("ix_document_templates_contexto"), table_name="document_templates")
    op.drop_index(op.f("ix_document_templates_id"), table_name="document_templates")
    op.drop_table("document_templates")
