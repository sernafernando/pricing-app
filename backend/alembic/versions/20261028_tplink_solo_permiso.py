"""Add permiso tplink.solo

`tplink.solo` is the TP-only data lock: the user only sees the sales of the
TP-Link store group (the `tplink` clave in `ml_tiendas_oficiales`), costed at
the TP cost, and never the Gauss figures. Enforced server-side. Granted to no
role; give it per user. It is an opt-in code (OPT_IN_PERMISSION_CODES), so
SUPERADMIN has it only when granted.

Revision ID: 20261028_tplink_solo_permiso
Revises: 20261027_tp_metrics_columns
Create Date: 2026-10-28

"""

from alembic import op

revision = "20261028_tplink_solo_permiso"
down_revision = "20261027_tp_metrics_columns"
branch_labels = None
depends_on = None

CODIGO = "tplink.solo"


def upgrade() -> None:
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'tplink.solo',
            'Acceso solo TP-Link',
            'El usuario solo ve las ventas de la tienda TP-Link, con el costo TP, y nunca ve las cifras de Gauss',
            'ventas_ml',
            64,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = 'tplink.solo');
    """)
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = 'tplink.solo');
    """)
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'tplink.solo';
    """)
