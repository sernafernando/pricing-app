"""add productos.ver_tienda permiso

Revision ID: 20251212_142216
Revises: 38aea5ee4513
Create Date: 2025-12-12 14:22:16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251212_142216'
down_revision = 'b72e99fcc3c8'  # Fixed: was '38aea5ee4513' (invalid)
branch_labels = None
depends_on = None


def upgrade():
    """Agregar el permiso productos.ver_tienda al catálogo de permisos"""

    # Insertar el nuevo permiso
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
        VALUES (
            'productos.ver_tienda',
            'Ver tienda',
            'Acceso a la vista de tienda de productos',
            'productos',
            2,
            false
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # Actualizar el orden de los permisos existentes de productos que vienen después
    op.execute("""
        UPDATE permisos
        SET orden = orden + 1
        WHERE categoria = 'productos'
        AND orden >= 2
        AND codigo != 'productos.ver_tienda';
    """)


def downgrade():
    """Remover el permiso productos.ver_tienda"""

    # Eliminar el permiso
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'productos.ver_tienda';
    """)

    # Restaurar el orden de los permisos de productos
    op.execute("""
        UPDATE permisos
        SET orden = orden - 1
        WHERE categoria = 'productos'
        AND orden > 2;
    """)
