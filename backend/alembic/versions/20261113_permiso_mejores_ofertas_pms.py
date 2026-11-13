"""Add the permission for the grouped better-offers notifier of every PM

Permission:
- alertas.ver_mejores_ofertas_pms: see, in the top bar, how many active publications with better offers each PM
  has, and open each PM's filtered Publicaciones ML page (notificador-ofertas-pm S8).

Role grants:
- ADMIN: yes (SUPERADMIN has it implicitly)

Revision ID: 20261113_permiso_mejores_ofertas_pms
Revises: 20261112_productos_erp_normalized_brand_category_index
Create Date: 2026-11-13

"""

from alembic import op

revision = "20261113_permiso_mejores_ofertas_pms"
down_revision = "20261112_productos_erp_normalized_brand_category_index"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "alertas.ver_mejores_ofertas_pms",
        "Ver mejores ofertas de todos los PMs",
        "Ver en la barra superior cuántas publicaciones activas con mejores ofertas tiene cada PM",
        "alertas",
        44,
        False,
    ),
]

ROL_PERMISOS = {
    "ADMIN": ["alertas.ver_mejores_ofertas_pms"],
}


def upgrade() -> None:
    for codigo, nombre, desc, cat, orden, critico in PERMISOS:
        critico_str = "true" if critico else "false"
        op.execute(f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES
                ('{codigo}', '{nombre}', '{desc}', '{cat}', {orden}, {critico_str}, NOW())
            ON CONFLICT (codigo) DO NOTHING;
        """)

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
    codigos_str = ", ".join(f"'{p[0]}'" for p in PERMISOS)

    op.execute(f"""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo IN ({codigos_str}));
    """)
    op.execute(f"""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo IN ({codigos_str}));
    """)
    op.execute(f"DELETE FROM permisos WHERE codigo IN ({codigos_str});")
