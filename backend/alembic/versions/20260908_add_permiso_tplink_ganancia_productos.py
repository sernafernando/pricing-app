"""Add permiso dashboard_tplink.ver_ganancia_productos

Splits the TP-Link margin gate: `dashboard_tplink.ver_ganancia` keeps covering
the general figures (KPIs, categories, operations), while the new permission
gates ganancia/markup on the Top Productos tables only. Nobody gets it by role
because those figures are currently miscalculated; grant it per user once the
calculation is fixed.

Revision ID: 20260908_tplink_ganancia_prod
Revises: 20260908_ml_payment_charges_type_nullable
Create Date: 2026-09-08

"""

from alembic import op

revision = "20260908_tplink_ganancia_prod"
down_revision = "20260908_ml_payment_charges_type_nullable"
branch_labels = None
depends_on = None

CODIGO = "dashboard_tplink.ver_ganancia_productos"


def upgrade() -> None:
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'dashboard_tplink.ver_ganancia_productos',
            'Ver ganancia por producto TP-Link',
            'Ver ganancia y markup en las tablas Top Productos de la vista TP-Link',
            'ventas_ml',
            62,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = 'dashboard_tplink.ver_ganancia_productos');
    """)
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = 'dashboard_tplink.ver_ganancia_productos');
    """)
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'dashboard_tplink.ver_ganancia_productos';
    """)
