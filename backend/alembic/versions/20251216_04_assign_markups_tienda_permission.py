"""assign productos.gestionar_markups_tienda to roles

Revision ID: 20251216_roles_04
Revises: 20251216_roles_03
Create Date: 2025-12-16

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251216_roles_04'
down_revision = '20251216_roles_03'
branch_labels = None
depends_on = None


def upgrade():
    """Asignar el permiso productos.gestionar_markups_tienda a roles ADMIN y PRICING"""

    # ADMIN obtiene el permiso de gestionar markups de tienda
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo = 'productos.gestionar_markups_tienda'
        ON CONFLICT DO NOTHING
    """)

    # PRICING también obtiene el permiso (para configurar markups)
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo = 'PRICING'
        AND p.codigo = 'productos.gestionar_markups_tienda'
        ON CONFLICT DO NOTHING
    """)


def downgrade():
    """Remover el permiso de los roles"""
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id = (SELECT id FROM permisos WHERE codigo = 'productos.gestionar_markups_tienda')
        AND rol_id IN (SELECT id FROM roles WHERE codigo IN ('ADMIN', 'PRICING'))
    """)
