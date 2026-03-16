"""Add seguimiento_envios.flag and seguimiento_envios.marcar_retornado permissions

Separate flag/retornado actions from envios_flex.config so users with
seguimiento_envios.ver (e.g. VENTAS) can flag and mark shipments as
returned without needing the critical envios_flex.config permission.

Permissions:
- seguimiento_envios.flag: flag/unflag shipments from Seguimiento view
- seguimiento_envios.marcar_retornado: mark/unmark returned from Seguimiento view

Assigned to: ADMIN, GERENTE, VENTAS

Revision ID: 20260316d1
Revises: 20260316c1
Create Date: 2026-03-16

"""

from alembic import op

revision = "20260316d1"
down_revision = "20260316c1"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "seguimiento_envios.flag",
        "Flaggear envíos (seguimiento)",
        "Marcar/desmarcar envíos con flag desde la vista de seguimiento de envíos",
        "envios_flex",
        116,
        False,
    ),
    (
        "seguimiento_envios.marcar_retornado",
        "Marcar envíos como retornado (seguimiento)",
        "Marcar/desmarcar envíos como retornado desde la vista de seguimiento de envíos",
        "envios_flex",
        117,
        False,
    ),
]

ROL_PERMISOS = {
    "ADMIN": [
        "seguimiento_envios.flag",
        "seguimiento_envios.marcar_retornado",
    ],
    "GERENTE": [
        "seguimiento_envios.flag",
        "seguimiento_envios.marcar_retornado",
    ],
    "VENTAS": [
        "seguimiento_envios.flag",
        "seguimiento_envios.marcar_retornado",
    ],
}


def upgrade():
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
