"""Agregar permiso produccion.prearmar_combos para el modulo de Prearmado

Revision ID: 20260513_permiso_prearmar_combos
Revises: 20260513_items_config_serializable
Create Date: 2026-05-13

"""

from alembic import op


revision = "20260513_permiso_prearmar_combos"
down_revision = "20260513_items_config_serializable"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Insertar el permiso nuevo
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'produccion.prearmar_combos',
            'Prearmar combos',
            'Acceso al módulo /prearmado: crear prearmados de combos cargando seriales por componente, validarlos contra ERP, consultar histórico y matchear con sales orders',
            'productos',
            67,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 2. Asignar al rol ADMIN. Otros roles (operadores de depósito) se asignan
    # manualmente desde el panel de permisos según corresponda.
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
          AND p.codigo = 'produccion.prearmar_combos'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    # 1. Limpiar asignaciones de rol
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'produccion.prearmar_combos'
        );
    """)

    # 2. Limpiar overrides de usuario (si hay)
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'produccion.prearmar_combos'
        );
    """)

    # 3. Eliminar el permiso
    op.execute("""
        DELETE FROM permisos
        WHERE codigo = 'produccion.prearmar_combos';
    """)
