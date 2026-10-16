"""Add permiso tplink.tema

`tplink.tema` only turns on the TP-Link theme (colors and logo across the
interface). It carries no data restriction: the TP-only data lock is
`tplink.solo`, which comes later. Granted to no role; give it per user.

NOTE: chained on the current head of main; re-chain on top of the sell-in
permissions migration once that PR merges.

Revision ID: 20261026_tplink_tema_permiso
Revises: 20261024_sell_in_tables
Create Date: 2026-10-26

"""

from alembic import op

revision = "20261026_tplink_tema_permiso"
down_revision = "20261024_sell_in_tables"
branch_labels = None
depends_on = None

CODIGO = "tplink.tema"


def upgrade() -> None:
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'tplink.tema',
            'Ver tema TP-Link',
            'Aplica los colores y el logo de TP-Link en toda la interfaz',
            'ventas_ml',
            63,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = 'tplink.tema');
    """)
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = 'tplink.tema');
    """)
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'tplink.tema';
    """)
