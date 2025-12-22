"""add permisos de clientes

Revision ID: add_permisos_clientes
Revises: add_ordenes_preparacion
Create Date: 2025-01-22

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'add_permisos_clientes'
down_revision = 'add_ordenes_preparacion'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Insertar nuevos permisos de clientes
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
        VALUES 
            (
                'clientes.ver',
                'Ver clientes',
                'Acceso a la lista de clientes y sus detalles',
                'clientes',
                70,
                false
            ),
            (
                'clientes.exportar',
                'Exportar clientes',
                'Exportar datos de clientes a CSV',
                'clientes',
                71,
                false
            )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # Asignar a roles SUPERADMIN, ADMIN y GERENTE
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo IN ('SUPERADMIN', 'ADMIN', 'GERENTE')
        AND p.codigo IN ('clientes.ver', 'clientes.exportar')
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    # Eliminar asignaciones a roles
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos 
            WHERE codigo IN ('clientes.ver', 'clientes.exportar')
        );
    """)

    # Eliminar permisos
    op.execute("""
        DELETE FROM permisos 
        WHERE codigo IN ('clientes.ver', 'clientes.exportar');
    """)
