"""add productos.exportar_pvp permission

Revision ID: 20260123_exportar_pvp
Revises: 20260123_merge_pvp
Create Date: 2026-01-23

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260123_exportar_pvp'
down_revision = '20260123_merge_pvp'
branch_labels = None
depends_on = None


def upgrade():
    # Insertar nuevo permiso
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
        VALUES (
            'productos.exportar_pvp',
            'Exportar PVP',
            'Exportar lista de precios PVP (clásica + cuotas)',
            'productos',
            16,
            false
        )
        ON CONFLICT (codigo) DO NOTHING
    """)

    # Asignar permiso a rol ADMIN (solo si no existe)
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo = 'productos.exportar_pvp'
        AND NOT EXISTS (
            SELECT 1 FROM roles_permisos_base rpb
            WHERE rpb.rol_id = r.id AND rpb.permiso_id = p.id
        )
    """)

    # Asignar permiso a rol VENTAS (solo si no existe)
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo = 'VENTAS'
        AND p.codigo = 'productos.exportar_pvp'
        AND NOT EXISTS (
            SELECT 1 FROM roles_permisos_base rpb
            WHERE rpb.rol_id = r.id AND rpb.permiso_id = p.id
        )
    """)


def downgrade():
    # Eliminar permiso de roles
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'productos.exportar_pvp'
        )
    """)

    # Eliminar permiso
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'productos.exportar_pvp'
    """)
