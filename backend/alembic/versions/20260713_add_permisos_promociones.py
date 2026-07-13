"""Agregar permisos para ML Seller Promotions

Permisos:
- promos.ver: ver promociones y su estado (ML Central de Promociones)
- promos.escribir: enrolar/remover items de promociones (kill-switch
  PROMOS_WRITE_ENABLED en app aparte; el permiso solo gatea el endpoint)

Asignaciones por rol:
- ADMIN: sí (ambos)
- GERENTE: sí (ambos)
- PRICING: sí (ambos)

`promos.escribir` se declara acá (junto con `promos.ver`) para que PR2
(write path) sea puramente aditivo — no requiere otra migración de catálogo.

Revision ID: 20260713_permisos_promociones
Revises: 20260701_deposito_msg
Create Date: 2026-07-13

"""

from alembic import op

revision = "20260713_permisos_promociones"
down_revision = "20260701_deposito_msg"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "promos.ver",
        "Ver promociones ML",
        "Ver promociones del vendedor y su estado (ML Central de Promociones)",
        "promos",
        44,
        False,
    ),
    (
        "promos.escribir",
        "Enrolar/remover promociones ML",
        "Enrolar o remover items en promociones (SELLER_CAMPAIGN, DEAL)",
        "promos",
        45,
        True,
    ),
]

ROL_PERMISOS = {
    "ADMIN": ["promos.ver", "promos.escribir"],
    "GERENTE": ["promos.ver", "promos.escribir"],
    "PRICING": ["promos.ver", "promos.escribir"],
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
