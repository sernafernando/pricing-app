"""Agregar permiso produccion.ver_combos para la nueva página de Producción

Revision ID: 20260508_produccion_ver_combos
Revises: 20260508_pli_storage
Create Date: 2026-05-08

"""

from alembic import op


revision = "20260508_produccion_ver_combos"
down_revision = "20260508_pli_storage"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Insertar el permiso nuevo
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'produccion.ver_combos',
            'Ver página Producción',
            'Acceso a la página /produccion (combos en armado, vista filtrada con spoilers de componentes)',
            'productos',
            66,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 2. Asignar al rol ADMIN. Otros roles (operadores de producción) se asignan
    # manualmente desde el panel de permisos según corresponda.
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
          AND p.codigo = 'produccion.ver_combos'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    # 1. Limpiar asignaciones de rol
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'produccion.ver_combos'
        );
    """)

    # 2. Limpiar overrides de usuario (si hay)
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'produccion.ver_combos'
        );
    """)

    # 3. Eliminar el permiso
    op.execute("""
        DELETE FROM permisos
        WHERE codigo = 'produccion.ver_combos';
    """)
