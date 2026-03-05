"""Agregar permisos del módulo RMA Seguimiento

Permisos:
- rma.ver: acceder al listado, ver casos, historial, stats
- rma.gestionar: crear, editar casos e items
- rma.admin_opciones: gestionar dropdowns de opciones
- rma.eliminar: soft-delete de casos (acción crítica)

Asignaciones por rol:
- ADMIN: todos
- GERENTE: ver, gestionar
- VENTAS: ver, gestionar
- LOGISTICA: ver, gestionar

Revision ID: 20260305_permisos_rma
Revises: 20260304_rma_soft_delete
Create Date: 2026-03-05

"""

from alembic import op

revision = "20260305_permisos_rma"
down_revision = "20260304_rma_soft_delete"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "rma.ver",
        "Ver RMA",
        "Acceder al módulo RMA Seguimiento: listado, casos, historial y estadísticas",
        "rma",
        60,
        False,
    ),
    ("rma.gestionar", "Gestionar RMA", "Crear, editar casos e items de RMA", "rma", 61, False),
    (
        "rma.admin_opciones",
        "Admin opciones RMA",
        "Gestionar dropdowns y opciones configurables del módulo RMA",
        "rma",
        62,
        True,
    ),
    ("rma.eliminar", "Eliminar RMA", "Eliminar (soft-delete) casos de RMA", "rma", 63, True),
]

# Qué roles reciben cada permiso
ROL_PERMISOS = {
    "ADMIN": ["rma.ver", "rma.gestionar", "rma.admin_opciones", "rma.eliminar"],
    "GERENTE": ["rma.ver", "rma.gestionar"],
    "VENTAS": ["rma.ver", "rma.gestionar"],
    "LOGISTICA": ["rma.ver", "rma.gestionar"],
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
