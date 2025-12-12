"""add productos.gestionar_markups_tienda permiso

Revision ID: 20251212_143711
Revises: 20251212_142216
Create Date: 2025-12-12 14:37:11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251212_143711'
down_revision = '20251212_142216'
branch_labels = None
depends_on = None


def upgrade():
    """Agregar el permiso productos.gestionar_markups_tienda al catálogo de permisos"""

    # Insertar el nuevo permiso
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
        VALUES (
            'productos.gestionar_markups_tienda',
            'Gestionar markups de tienda',
            'Configurar y modificar markups en la vista de tienda',
            'productos',
            3,
            true
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # Actualizar el orden de los permisos existentes de productos que vienen después
    op.execute("""
        UPDATE permisos
        SET orden = orden + 1
        WHERE categoria = 'productos'
        AND orden >= 3
        AND codigo NOT IN ('productos.ver_tienda', 'productos.gestionar_markups_tienda');
    """)


def downgrade():
    """Remover el permiso productos.gestionar_markups_tienda"""

    # Eliminar el permiso
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'productos.gestionar_markups_tienda';
    """)

    # Restaurar el orden de los permisos de productos
    op.execute("""
        UPDATE permisos
        SET orden = orden - 1
        WHERE categoria = 'productos'
        AND orden > 3;
    """)
