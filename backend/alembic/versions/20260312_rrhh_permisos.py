"""Add RRHH permissions: rrhh.ver, rrhh.gestionar, rrhh.config

Extends the categoriapermiso PG enum with 'rrhh', inserts
3 permissions into the catalog, and assigns them to ADMIN role.

Revision ID: 20260312_rrhh_permisos
Revises: 20260312_rrhh_empleados
Create Date: 2026-03-12

"""

from alembic import op

revision = "20260312_rrhh_permisos"
down_revision = "20260312_rrhh_empleados"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "rrhh.ver",
        "Ver módulo RRHH",
        "Acceso de lectura al módulo de Recursos Humanos: empleados, legajos, documentos",
        "rrhh",
        120,
        False,
    ),
    (
        "rrhh.gestionar",
        "Gestionar empleados",
        "Crear, editar y dar de baja empleados. Subir y eliminar documentos del legajo",
        "rrhh",
        121,
        False,
    ),
    (
        "rrhh.config",
        "Configurar RRHH",
        "Administrar tipos de documento y campos custom del legajo",
        "rrhh",
        122,
        True,
    ),
]

# Roles that get RRHH permissions
ROL_PERMISOS = {
    "ADMIN": ["rrhh.ver", "rrhh.gestionar", "rrhh.config"],
}


def upgrade():
    # categoria is String(50), not a PG enum — no ALTER TYPE needed.
    # Just insert permissions directly.
    
    # 1. Insert permissions into catalog
    for codigo, nombre, desc, cat, orden, critico in PERMISOS:
        critico_str = "true" if critico else "false"
        op.execute(f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES
                ('{codigo}', '{nombre}', '{desc}', '{cat}', {orden}, {critico_str}, NOW())
            ON CONFLICT (codigo) DO NOTHING;
        """)

    # 2. Assign to roles
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


def downgrade():
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
    # Note: PostgreSQL does not support removing values from an enum type.
    # The 'rrhh' value will remain in categoriapermiso but is harmless.
