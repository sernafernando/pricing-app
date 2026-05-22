"""compras_034: seed permiso administracion.wipe_compras_testing

Revision ID: compras_034_wipe_permiso
Revises: compras_033_op_banco
Create Date: 2026-05-22

"""

from alembic import op

# revision identifiers
revision = "compras_034_wipe_permiso"
down_revision = "compras_033_op_banco"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Inserta el permiso wipe_compras_testing y lo asigna a SUPERADMIN y ADMIN."""

    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
        VALUES (
            'administracion.wipe_compras_testing',
            'Limpiar tablas de compras (testing)',
            'Elimina todos los datos del módulo compras. Solo para entornos de prueba.',
            'administracion',
            99,
            true
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # Asignar a SUPERADMIN (rol_id=1) y ADMIN (rol_id=2) via roles_permisos_base
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE p.codigo = 'administracion.wipe_compras_testing'
          AND r.codigo IN ('SUPERADMIN', 'ADMIN')
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    """Elimina el permiso y sus asignaciones de roles."""

    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id = (
            SELECT id FROM permisos WHERE codigo = 'administracion.wipe_compras_testing'
        );
    """)

    op.execute("""
        DELETE FROM permisos WHERE codigo = 'administracion.wipe_compras_testing';
    """)
