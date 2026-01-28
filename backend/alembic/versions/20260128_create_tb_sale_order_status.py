"""create_tb_sale_order_status

Revision ID: 20260128_sale_order_status
Revises: 
Create Date: 2026-01-28

Crea tabla tb_sale_order_status para mapeo de estados de pedidos.
Sincronizado desde vwSaleOrderStatus del ERP.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260128_sale_order_status'
down_revision = '20250127_tienda_oficial'
branch_labels = None
depends_on = None


def upgrade():
    """Crea tabla tb_sale_order_status"""
    op.create_table(
        'tb_sale_order_status',
        sa.Column('ssos_id', sa.Integer(), nullable=False),
        sa.Column('ssos_name', sa.String(length=100), nullable=False),
        sa.Column('ssos_description', sa.String(length=255), nullable=True),
        sa.Column('ssos_isActive', sa.Boolean(), nullable=True, default=True),
        
        # Campos locales para categorización
        sa.Column('ssos_category', sa.String(length=50), nullable=True),
        sa.Column('ssos_color', sa.String(length=20), nullable=True),
        sa.Column('ssos_order', sa.Integer(), nullable=True),
        
        sa.PrimaryKeyConstraint('ssos_id')
    )
    
    # Crear índice para búsquedas rápidas por categoría
    op.create_index('ix_tb_sale_order_status_category', 'tb_sale_order_status', ['ssos_category'])
    
    # Insertar datos conocidos
    # Categorías:
    # - pendiente_verificacion: Ventas (verificar)
    # - pendiente_comercial: Ventas (confirmar/aprobar)
    # - pendiente_deposito: Depósito (armar)
    # - completado: Facturación
    # - rma: RMA (sector aparte)
    op.execute("""
        INSERT INTO tb_sale_order_status (ssos_id, ssos_name, ssos_category, ssos_color, ssos_order) VALUES
        (2, 'Pendiente Web', 'pendiente_comercial', '#FFA500', 1),
        (10, 'En Area Comercial', 'pendiente_comercial', '#FFC107', 2),
        (20, 'En Preparación', 'pendiente_deposito', '#FF6B6B', 3),
        (50, 'Ok Para Emisión', 'completado', '#4CAF50', 4),
        (200, 'RMA en Preparación', 'rma', '#9C27B0', 5),
        (201, 'RMA preparado', 'rma', '#7B1FA2', 6)
    """)


def downgrade():
    """Elimina tabla tb_sale_order_status"""
    op.drop_index('ix_tb_sale_order_status_category', 'tb_sale_order_status')
    op.drop_table('tb_sale_order_status')
