"""Create cuentas_corrientes_proveedores table

Revision ID: 20260211_cc_prov
Revises: 20260211_offset_flex
Create Date: 2026-02-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260211_cc_prov'
down_revision = '20260211_offset_flex'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cuentas_corrientes_proveedores',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('bra_id', sa.Integer(), nullable=False),
        sa.Column('id_proveedor', sa.Integer(), nullable=False),
        sa.Column('proveedor', sa.String(255), nullable=False),
        sa.Column('monto_total', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('monto_abonado', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('pendiente', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_cc_prov_bra_id', 'cuentas_corrientes_proveedores', ['bra_id'])
    op.create_index('ix_cc_prov_id_proveedor', 'cuentas_corrientes_proveedores', ['id_proveedor'])


def downgrade():
    op.drop_index('ix_cc_prov_id_proveedor', table_name='cuentas_corrientes_proveedores')
    op.drop_index('ix_cc_prov_bra_id', table_name='cuentas_corrientes_proveedores')
    op.drop_table('cuentas_corrientes_proveedores')
