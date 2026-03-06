"""Agregar permiso para ver alertas de free shipping error

Permiso:
- alertas.ver_free_shipping: ver alertas de publicaciones con envío gratis
  activado pero precio rebate < $33.000

Asignaciones por rol:
- ADMIN: sí
- GERENTE: sí
- PRICING: sí

Revision ID: 20260306_permiso_free_shipping
Revises: 20260306_permisos_ver_ganancia
Create Date: 2026-03-06

"""

from alembic import op

revision = "20260306_permiso_free_shipping"
down_revision = "20260306_permisos_ver_ganancia"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "alertas.ver_free_shipping",
        "Ver alertas envío gratis",
        "Ver publicaciones con envío gratis activado y precio rebate menor a $33.000",
        "alertas",
        43,
        False,
    ),
]

ROL_PERMISOS = {
    "ADMIN": ["alertas.ver_free_shipping"],
    "GERENTE": ["alertas.ver_free_shipping"],
    "PRICING": ["alertas.ver_free_shipping"],
}


def upgrade():
    # 1. Insertar permiso en catálogo
    for codigo, nombre, desc, cat, orden, critico in PERMISOS:
        critico_str = "true" if critico else "false"
        op.execute(f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES
                ('{codigo}', '{nombre}', '{desc}', '{cat}', {orden}, {critico_str}, NOW())
            ON CONFLICT (codigo) DO NOTHING;
        """)

    # 2. Asignar a roles
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
