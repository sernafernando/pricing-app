"""create tb_pedidos_export table

Revision ID: 20251223_115500
Revises: 20251223_105119
Create Date: 2025-12-23 11:55:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251223_115500'
down_revision = '20251223_105119'
branch_labels = None
depends_on = None


def upgrade():
    """
    Crea tabla tb_pedidos_export para guardar pedidos del Export 87.
    Tabla SIMPLE - guarda TAL CUAL los datos del ERP sin transformaciones.
    """
    op.create_table(
        'tb_pedidos_export',
        sa.Column('id_pedido', sa.Integer(), nullable=False, comment='IDPedido del ERP'),
        sa.Column('item_id', sa.Integer(), nullable=False, comment='ID del item/producto'),
        
        # Cliente
        sa.Column('id_cliente', sa.Integer(), nullable=True),
        sa.Column('nombre_cliente', sa.Text(), nullable=True),
        
        # Item
        sa.Column('cantidad', sa.Numeric(10, 2), nullable=True),
        
        # Envío
        sa.Column('tipo_envio', sa.Text(), nullable=True),
        sa.Column('direccion_envio', sa.Text(), nullable=True),
        sa.Column('fecha_envio', sa.DateTime(), nullable=True),
        
        # Observaciones
        sa.Column('observaciones', sa.Text(), nullable=True),
        
        # TiendaNube
        sa.Column('orden_tn', sa.Text(), nullable=True, comment='Número visible en TN (ej: NRO-12345)'),
        sa.Column('order_id_tn', sa.Text(), nullable=True, comment='orderID de TN para API'),
        
        # Control
        sa.Column('activo', sa.Boolean(), nullable=False, server_default='true', comment='true = activo en export, false = archivado'),
        sa.Column('fecha_sync', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        
        # Primary Key compuesta
        sa.PrimaryKeyConstraint('id_pedido', 'item_id', name='pk_pedidos_export')
    )
    
    # Índices para performance
    op.create_index('idx_pedidos_export_activo', 'tb_pedidos_export', ['activo'])
    op.create_index('idx_pedidos_export_order_id_tn', 'tb_pedidos_export', ['order_id_tn'])
    op.create_index('idx_pedidos_export_id_cliente', 'tb_pedidos_export', ['id_cliente'])
    op.create_index('idx_pedidos_export_fecha_envio', 'tb_pedidos_export', ['fecha_envio'])


def downgrade():
    """Elimina la tabla tb_pedidos_export"""
    op.drop_index('idx_pedidos_export_fecha_envio', table_name='tb_pedidos_export')
    op.drop_index('idx_pedidos_export_id_cliente', table_name='tb_pedidos_export')
    op.drop_index('idx_pedidos_export_order_id_tn', table_name='tb_pedidos_export')
    op.drop_index('idx_pedidos_export_activo', table_name='tb_pedidos_export')
    op.drop_table('tb_pedidos_export')
