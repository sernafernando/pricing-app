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
    # Insertar permiso — tabla permisos usa: codigo, nombre, descripcion, categoria, orden, es_critico
    op.execute(
        """
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
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

    # Asignar a roles ADMIN, SUPERADMIN, VENTAS
    # roles_permisos_base tiene rol_id (FK a roles.id) y permiso_id (FK a permisos.id)
    op.execute(
        """
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo IN ('SUPERADMIN', 'ADMIN', 'VENTAS')
          AND p.codigo = 'tienda.exportar_lista_sugerido'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM roles_permisos_base
        WHERE permiso_id = (SELECT id FROM permisos WHERE codigo = 'tienda.exportar_lista_sugerido')
        """
    )
    op.execute("DELETE FROM permisos WHERE codigo = 'tienda.exportar_lista_sugerido'")
