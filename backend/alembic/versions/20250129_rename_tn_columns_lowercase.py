"""rename tiendanube columns to lowercase

Revision ID: 20250129_tn_lowercase
Revises: 20250129_sale_order_times
Create Date: 2025-01-29

Renombra columnas de tb_tiendanube_orders a minúsculas para evitar
problemas con case-sensitivity en PostgreSQL.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20250129_tn_lowercase'
down_revision = '20250129_sale_order_times'
branch_labels = None
depends_on = None


def upgrade():
    """Renombra columnas a minúsculas"""
    # Renombrar columnas con mayúsculas
    op.alter_column('tb_tiendanube_orders', 'tno_orderID', new_column_name='tno_orderid')
    op.alter_column('tb_tiendanube_orders', 'tno_JSon', new_column_name='tno_json')
    op.alter_column('tb_tiendanube_orders', 'tno_isCancelled', new_column_name='tno_iscancelled')
    
    # Recrear índice con nuevo nombre de columna
    op.drop_index('ix_tb_tiendanube_orders_tno_orderID', 'tb_tiendanube_orders')
    op.create_index('ix_tb_tiendanube_orders_tno_orderid', 'tb_tiendanube_orders', ['tno_orderid'])


def downgrade():
    """Revierte los nombres a mayúsculas"""
    op.alter_column('tb_tiendanube_orders', 'tno_orderid', new_column_name='tno_orderID')
    op.alter_column('tb_tiendanube_orders', 'tno_json', new_column_name='tno_JSon')
    op.alter_column('tb_tiendanube_orders', 'tno_iscancelled', new_column_name='tno_isCancelled')
    
    # Recrear índice con nombre original
    op.drop_index('ix_tb_tiendanube_orders_tno_orderid', 'tb_tiendanube_orders')
    op.create_index('ix_tb_tiendanube_orders_tno_orderID', 'tb_tiendanube_orders', ['tno_orderID'])
