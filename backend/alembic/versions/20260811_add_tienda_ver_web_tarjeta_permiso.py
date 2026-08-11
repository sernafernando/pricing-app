"""tienda.ver_web_tarjeta permission (Web Tarjeta column visibility)

The Web Tarjeta column exposes the card price derived from the transfer price,
which not every operator on the Tienda grid should see. This adds a dedicated
READ permission for that one column — it gates visibility only, no write path
changes.

Category `productos` and the 4x orden band match the existing `tienda.*`
permissions seeded by 20251216_03_add_granular_permissions (orden 40/41/42),
so this slots in at 43 without renumbering anything. `es_critico=False`: it
hides a derived display value, it does not authorize a mutation.

Revision ID: 20260811_ver_web_tarjeta
Revises: 20260811_porcentaje_tarjeta_tn
Create Date: 2026-08-11 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260811_ver_web_tarjeta"
down_revision = "20260811_porcentaje_tarjeta_tn"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('tienda.ver_web_tarjeta', 'Ver columna Web Tarjeta', 'Ver la columna Web Tarjeta en la vista tienda', 'productos', 43, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo = 'tienda.ver_web_tarjeta'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'tienda.ver_web_tarjeta'
        );
    """)
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'tienda.ver_web_tarjeta';
    """)
