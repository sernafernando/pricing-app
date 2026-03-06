"""Agregar permisos para ver montos de ganancia en dashboards

Permisos:
- ventas_ml.ver_ganancia: ver montos $ de ganancia en métricas y rentabilidad ML
- ventas_fuera.ver_ganancia: ver montos $ de ganancia en métricas y rentabilidad Fuera ML
- ventas_tn.ver_ganancia: ver montos $ de ganancia en métricas y rentabilidad Tienda Nube

Nota: estos permisos NO afectan la visibilidad de markup %.
Solo ocultan los valores en pesos de ganancia.

Asignaciones por rol:
- ADMIN: todos (via wildcard ventas_*)
- GERENTE: todos
- PRICING: todos
- VENTAS: ninguno (no ven ganancia por defecto)

Revision ID: 20260306_permisos_ver_ganancia
Revises: 20260305_rma_envio_cli
Create Date: 2026-03-06

"""

from alembic import op

revision = "20260306_permisos_ver_ganancia"
down_revision = "20260305_rma_envio_cli"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "ventas_ml.ver_ganancia",
        "Ver ganancia ML",
        "Ver montos de ganancia en métricas y rentabilidad ML (no afecta markup %)",
        "ventas_ml",
        14,
        False,
    ),
    (
        "ventas_fuera.ver_ganancia",
        "Ver ganancia Fuera ML",
        "Ver montos de ganancia en métricas y rentabilidad fuera de ML (no afecta markup %)",
        "ventas_fuera",
        25,
        False,
    ),
    (
        "ventas_tn.ver_ganancia",
        "Ver ganancia Tienda Nube",
        "Ver montos de ganancia en métricas y rentabilidad Tienda Nube (no afecta markup %)",
        "ventas_tn",
        34,
        False,
    ),
]

# Qué roles reciben cada permiso
ROL_PERMISOS = {
    "ADMIN": [
        "ventas_ml.ver_ganancia",
        "ventas_fuera.ver_ganancia",
        "ventas_tn.ver_ganancia",
    ],
    "GERENTE": [
        "ventas_ml.ver_ganancia",
        "ventas_fuera.ver_ganancia",
        "ventas_tn.ver_ganancia",
    ],
    "PRICING": [
        "ventas_ml.ver_ganancia",
        "ventas_fuera.ver_ganancia",
        "ventas_tn.ver_ganancia",
    ],
}


def upgrade():
    # 1. Insertar permisos en catálogo
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
