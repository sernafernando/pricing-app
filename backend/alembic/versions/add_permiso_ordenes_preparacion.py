"""add permiso ordenes.ver_preparacion

Revision ID: add_ordenes_preparacion
Revises:
Create Date: 2025-01-17

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'add_ordenes_preparacion'
down_revision = '20251216_roles_03'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Insertar nuevo permiso
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
        VALUES (
            'ordenes.ver_preparacion',
            'Ver pedidos en preparación',
            'Permite ver el listado de pedidos listos para despachar',
            'ordenes',
            60,
            false
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # Asignar a roles SUPERADMIN, ADMIN, GERENTE
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo IN ('SUPERADMIN', 'ADMIN', 'GERENTE')
        AND p.codigo = 'ordenes.ver_preparacion'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    # Eliminar asignaciones a roles
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = 'ordenes.ver_preparacion');
    """)

    # Eliminar permiso
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'ordenes.ver_preparacion';
    """)
