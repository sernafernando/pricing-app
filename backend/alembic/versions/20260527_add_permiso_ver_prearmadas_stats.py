"""Agregar permiso produccion.ver_prearmadas_stats (ADMIN only)

Revision ID: 20260527_permiso_ver_prearmadas_stats
Revises: 20260527_prearmados_armado_idx
Create Date: 2026-05-27

Inserta el permiso ``produccion.ver_prearmadas_stats`` y lo asigna al rol ADMIN.

ADR-3: igual que ``produccion.ver_combos`` y ``produccion.prearmar_combos``,
el permiso se seedea SOLO al rol ADMIN. Los operadores asignan el permiso a
VENTAS / PRODUCCION manualmente desde el panel de permisos una vez desplegado
el feature.

Ver también: 20260513_add_permiso_prearmar_combos.py (patrón de referencia).
"""

from alembic import op

revision = "20260527_permiso_ver_prearmadas_stats"
down_revision = "20260527_prearmados_armado_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Insertar el permiso nuevo (idempotente)
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'produccion.ver_prearmadas_stats',
            'Ver stats de prearmados',
            'Acceso a contadores de prearmados armados (badges en productos y producción, página de prearmados disponibles para vendedores)',
            'productos',
            68,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 2. Asignar al rol ADMIN.
    # Otros roles (VENTAS, PRODUCCION) se asignan manualmente desde el panel
    # de permisos según corresponda al deploy — siguiendo el precedente de
    # produccion.ver_combos y produccion.prearmar_combos.
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
          AND p.codigo = 'produccion.ver_prearmadas_stats'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    # 1. Limpiar asignaciones de rol
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'produccion.ver_prearmadas_stats'
        );
    """)

    # 2. Limpiar overrides de usuario (si hay)
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'produccion.ver_prearmadas_stats'
        );
    """)

    # 3. Eliminar el permiso
    op.execute("""
        DELETE FROM permisos
        WHERE codigo = 'produccion.ver_prearmadas_stats';
    """)
