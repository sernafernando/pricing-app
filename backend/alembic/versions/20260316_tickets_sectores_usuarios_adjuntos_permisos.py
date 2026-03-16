"""Add tickets_sectores_usuarios M2M, tickets_adjuntos, and 4 ticket permissions

Revision ID: 20260316t1
Revises: 20260316d1
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa

revision = "20260316t1"
down_revision = "20260316d1"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "tickets.ver",
        "Ver tickets",
        "Acceso de lectura a tickets: listar, ver detalle, comentarios, historial",
        "tickets",
        130,
        False,
    ),
    (
        "tickets.crear",
        "Crear tickets",
        "Crear nuevos tickets y subir adjuntos",
        "tickets",
        131,
        False,
    ),
    (
        "tickets.gestionar",
        "Gestionar tickets",
        "Cambiar estado, asignar tickets, transiciones de workflow",
        "tickets",
        132,
        False,
    ),
    (
        "tickets.admin",
        "Administrar tickets",
        "Configurar sectores, workflows, asignar usuarios a sectores",
        "tickets",
        133,
        True,
    ),
]

ROL_PERMISOS = {
    "ADMIN": ["tickets.ver", "tickets.crear", "tickets.gestionar", "tickets.admin"],
    "GERENTE": ["tickets.ver", "tickets.crear", "tickets.gestionar"],
    "PRICING": ["tickets.ver", "tickets.crear"],
    "VENTAS": ["tickets.ver", "tickets.crear"],
}


def upgrade() -> None:
    # 1. Create tickets_sectores_usuarios M2M table
    op.create_table(
        "tickets_sectores_usuarios",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "sector_id",
            sa.Integer(),
            sa.ForeignKey("tickets_sectores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "usuario_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("sector_id", "usuario_id", name="uq_sector_usuario"),
    )
    op.create_index("ix_tickets_sectores_usuarios_sector_id", "tickets_sectores_usuarios", ["sector_id"])
    op.create_index("ix_tickets_sectores_usuarios_usuario_id", "tickets_sectores_usuarios", ["usuario_id"])

    # 2. Create tickets_adjuntos table
    op.create_table(
        "tickets_adjuntos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "ticket_id",
            sa.Integer(),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nombre_archivo", sa.String(255), nullable=False),
        sa.Column("path_archivo", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("tamano_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "subido_por_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_tickets_adjuntos_ticket_id", "tickets_adjuntos", ["ticket_id"])

    # 3. Insert ticket permissions into catalog
    for codigo, nombre, desc, cat, orden, critico in PERMISOS:
        critico_str = "true" if critico else "false"
        op.execute(f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES
                ('{codigo}', '{nombre}', '{desc}', '{cat}', {orden}, {critico_str}, NOW())
            ON CONFLICT (codigo) DO NOTHING;
        """)

    # 4. Assign to roles
    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            op.execute(f"""
                INSERT INTO roles_permisos_base (rol_id, permiso_id)
                SELECT r.id, p.id
                FROM roles r
                CROSS JOIN permisos p
                WHERE r.codigo = '{rol}'
                  AND p.codigo = '{codigo}'
                ON CONFLICT DO NOTHING;
            """)


def downgrade() -> None:
    # Drop tables
    op.drop_index("ix_tickets_adjuntos_ticket_id", table_name="tickets_adjuntos")
    op.drop_table("tickets_adjuntos")
    op.drop_index("ix_tickets_sectores_usuarios_usuario_id", table_name="tickets_sectores_usuarios")
    op.drop_index("ix_tickets_sectores_usuarios_sector_id", table_name="tickets_sectores_usuarios")
    op.drop_table("tickets_sectores_usuarios")

    # Remove permissions
    codigos = [p[0] for p in PERMISOS]
    codigos_str = ", ".join(f"'{c}'" for c in codigos)

    op.execute(f"""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo IN ({codigos_str})
        );
    """)

    op.execute(f"""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo IN ({codigos_str})
        );
    """)

    op.execute(f"""
        DELETE FROM permisos WHERE codigo IN ({codigos_str});
    """)
