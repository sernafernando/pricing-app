"""Agregar permiso para ver Seguimiento de Envíos

Permiso:
- seguimiento_envios.ver: vista readonly de etiquetas de envío con flaggeo
  y checkeo de colecta, para sectores que no son depósito

Asignaciones por rol:
- ADMIN: sí
- GERENTE: sí
- VENTAS: sí (este es el público objetivo)

Revision ID: 20260309_permiso_seg_envios
Revises: 20260309_flag_envio
Create Date: 2026-03-09

"""

from alembic import op

revision = "20260309_permiso_seg_envios"
down_revision = "20260309_flag_envio"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "seguimiento_envios.ver",
        "Ver seguimiento de envíos",
        "Vista readonly de etiquetas de envío con capacidad de flaggeo y checkeo de colecta",
        "envios_flex",
        50,
        False,
    ),
]

ROL_PERMISOS = {
    "ADMIN": ["seguimiento_envios.ver"],
    "GERENTE": ["seguimiento_envios.ver"],
    "VENTAS": ["seguimiento_envios.ver"],
}


def upgrade():
    # 0. Ensure 'envios_flex' exists in the categoriapermiso enum
    op.execute("ALTER TYPE categoriapermiso ADD VALUE IF NOT EXISTS 'envios_flex'")
    # Commit so the new enum value is visible to subsequent statements
    op.execute("COMMIT")

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
