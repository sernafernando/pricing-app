"""add permiso tienda.exportar_lista_sugerido

Revision ID: 20260413_perm_sug
Revises: 20260413_markup_sug
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260413_perm_sug"
down_revision = "20260413_markup_sug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Insertar permiso
    op.execute(
        """
        INSERT INTO permisos (codigo, nombre, descripcion, modulo, orden, es_base)
        VALUES (
            'tienda.exportar_lista_sugerido',
            'Exportar lista sugerido',
            'Exportar lista de precios sugerido',
            'productos',
            18,
            false
        )
        ON CONFLICT (codigo) DO NOTHING
        """
    )

    # Asignar a roles ADMIN y VENTAS (mismos que exportar_lista_gremio)
    op.execute(
        """
        INSERT INTO roles_permisos (rol, permiso_id)
        SELECT r.rol, p.id
        FROM (VALUES ('ADMIN'), ('SUPERADMIN'), ('VENTAS')) AS r(rol)
        CROSS JOIN permisos p
        WHERE p.codigo = 'tienda.exportar_lista_sugerido'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM roles_permisos
        WHERE permiso_id = (SELECT id FROM permisos WHERE codigo = 'tienda.exportar_lista_sugerido')
        """
    )
    op.execute("DELETE FROM permisos WHERE codigo = 'tienda.exportar_lista_sugerido'")
