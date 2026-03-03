"""Add envios_flex.asignar_turbo and envios_flex.asignar_lluvia permissions

Separate turbo/lluvia toggle actions from envios_flex.config so depot
operators can mark shipments without needing full config access.

Revision ID: 20260303_turbo_lluvia_perm
Revises: 20260303_traza_ver
Create Date: 2026-03-03

"""

from alembic import op

revision = "20260303_turbo_lluvia_perm"
down_revision = "20260303_traza_ver"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "envios_flex.asignar_turbo",
        "Marcar envíos como turbo",
        "Marcar/desmarcar etiquetas como turbo (individual y masivo)",
        "envios_flex",
        110,
    ),
    (
        "envios_flex.asignar_lluvia",
        "Marcar envíos como lluvia",
        "Marcar/desmarcar etiquetas como lluvia (individual y masivo)",
        "envios_flex",
        111,
    ),
]

# Roles that get these permissions by default
ROLES_ASIGNAR = ["ADMIN"]


def upgrade():
    # 1. Insert permissions into catalog
    for codigo, nombre, descripcion, categoria, orden in PERMISOS:
        op.execute(f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES
                ('{codigo}', '{nombre}', '{descripcion}', '{categoria}', {orden}, false, NOW())
            ON CONFLICT (codigo) DO NOTHING;
        """)

    # 2. Assign to roles
    for rol in ROLES_ASIGNAR:
        for codigo, _, _, _, _ in PERMISOS:
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
    for codigo, _, _, _, _ in PERMISOS:
        # Remove role assignments
        op.execute(f"""
            DELETE FROM roles_permisos_base
            WHERE permiso_id IN (
                SELECT id FROM permisos WHERE codigo = '{codigo}'
            );
        """)

        # Remove user overrides
        op.execute(f"""
            DELETE FROM usuarios_permisos_override
            WHERE permiso_id IN (
                SELECT id FROM permisos WHERE codigo = '{codigo}'
            );
        """)

        # Remove permission
        op.execute(f"""
            DELETE FROM permisos WHERE codigo = '{codigo}';
        """)
