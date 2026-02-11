"""Add reportes.ver_cuentas_corrientes permission

Revision ID: 20260211_cc_perm
Revises: 20260211_cc_cli
Create Date: 2026-02-11

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260211_cc_perm"
down_revision = "20260211_cc_cli"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Insert the permission
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('reportes.ver_cuentas_corrientes', 'Ver cuentas corrientes', 'Acceso al reporte de cuentas corrientes de proveedores y clientes', 'reportes', 44, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 2. Assign to ADMIN role
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo = 'reportes.ver_cuentas_corrientes'
        ON CONFLICT DO NOTHING;
    """)

    # 3. Assign to GERENTE role
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'GERENTE'
        AND p.codigo = 'reportes.ver_cuentas_corrientes'
        ON CONFLICT DO NOTHING;
    """)

    # 4. Assign to PRICING role
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'PRICING'
        AND p.codigo = 'reportes.ver_cuentas_corrientes'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    # Remove role assignments first
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'reportes.ver_cuentas_corrientes'
        );
    """)

    # Remove the permission
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'reportes.ver_cuentas_corrientes';
    """)
