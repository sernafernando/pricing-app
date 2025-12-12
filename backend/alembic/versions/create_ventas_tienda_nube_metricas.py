"""Create ventas_tienda_nube_metricas table

Revision ID: create_ventas_tn_metricas
Revises: add_aplica_tienda_nube
Create Date: 2025-12-09

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_ventas_tn_metricas'
down_revision = 'add_aplica_tienda_nube'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ventas_tienda_nube_metricas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('it_transaction', sa.BigInteger(), nullable=False),
        sa.Column('ct_transaction', sa.BigInteger(), nullable=True),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('codigo', sa.String(100), nullable=True),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('marca', sa.String(255), nullable=True),
        sa.Column('categoria', sa.String(255), nullable=True),
        sa.Column('subcategoria', sa.String(255), nullable=True),
        sa.Column('bra_id', sa.Integer(), nullable=True),
        sa.Column('sucursal', sa.String(255), nullable=True),
        sa.Column('sm_id', sa.Integer(), nullable=True),
        sa.Column('vendedor', sa.String(255), nullable=True),
        sa.Column('cust_id', sa.Integer(), nullable=True),
        sa.Column('cliente', sa.String(255), nullable=True),
        sa.Column('df_id', sa.Integer(), nullable=True),
        sa.Column('tipo_comprobante', sa.String(100), nullable=True),
        sa.Column('numero_comprobante', sa.String(50), nullable=True),
        sa.Column('fecha_venta', sa.DateTime(timezone=True), nullable=False),
        sa.Column('fecha_calculo', sa.Date(), nullable=True),
        sa.Column('sd_id', sa.Integer(), nullable=True),
        sa.Column('signo', sa.Integer(), nullable=True),
        sa.Column('cantidad', sa.Numeric(18, 4), nullable=False),
        sa.Column('monto_unitario', sa.Numeric(18, 2), nullable=True),
        sa.Column('monto_total', sa.Numeric(18, 2), nullable=False),
        sa.Column('iva_porcentaje', sa.Numeric(5, 2), nullable=True),
        sa.Column('monto_iva', sa.Numeric(18, 2), nullable=True),
        sa.Column('monto_con_iva', sa.Numeric(18, 2), nullable=True),
        sa.Column('costo_unitario', sa.Numeric(18, 6), nullable=True),
        sa.Column('costo_total', sa.Numeric(18, 2), nullable=True),
        sa.Column('moneda_costo', sa.String(10), nullable=True),
        sa.Column('cotizacion_dolar', sa.Numeric(10, 4), nullable=True),
        sa.Column('comision_porcentaje', sa.Numeric(5, 2), nullable=True),
        sa.Column('comision_monto', sa.Numeric(18, 2), nullable=True),
        sa.Column('ganancia', sa.Numeric(18, 2), nullable=True),
        sa.Column('markup_porcentaje', sa.Numeric(10, 2), nullable=True),
        sa.Column('es_combo', sa.Boolean(), nullable=True, default=False),
        sa.Column('combo_group_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Crear índices
    op.create_index('ix_ventas_tn_metricas_it_transaction', 'ventas_tienda_nube_metricas', ['it_transaction'], unique=True)
    op.create_index('ix_ventas_tn_metricas_ct_transaction', 'ventas_tienda_nube_metricas', ['ct_transaction'])
    op.create_index('ix_ventas_tn_metricas_item_id', 'ventas_tienda_nube_metricas', ['item_id'])
    op.create_index('ix_ventas_tn_metricas_marca', 'ventas_tienda_nube_metricas', ['marca'])
    op.create_index('ix_ventas_tn_metricas_categoria', 'ventas_tienda_nube_metricas', ['categoria'])
    op.create_index('ix_ventas_tn_metricas_bra_id', 'ventas_tienda_nube_metricas', ['bra_id'])
    op.create_index('ix_ventas_tn_metricas_sucursal', 'ventas_tienda_nube_metricas', ['sucursal'])
    op.create_index('ix_ventas_tn_metricas_sm_id', 'ventas_tienda_nube_metricas', ['sm_id'])
    op.create_index('ix_ventas_tn_metricas_vendedor', 'ventas_tienda_nube_metricas', ['vendedor'])
    op.create_index('ix_ventas_tn_metricas_cust_id', 'ventas_tienda_nube_metricas', ['cust_id'])
    op.create_index('ix_ventas_tn_metricas_fecha_venta', 'ventas_tienda_nube_metricas', ['fecha_venta'])
    op.create_index('ix_ventas_tn_metricas_fecha_calculo', 'ventas_tienda_nube_metricas', ['fecha_calculo'])
    op.create_index('ix_ventas_tn_metricas_combo_group_id', 'ventas_tienda_nube_metricas', ['combo_group_id'])


def downgrade():
    op.drop_index('ix_ventas_tn_metricas_combo_group_id', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_fecha_calculo', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_fecha_venta', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_cust_id', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_vendedor', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_sm_id', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_sucursal', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_bra_id', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_categoria', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_marca', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_item_id', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_ct_transaction', table_name='ventas_tienda_nube_metricas')
    op.drop_index('ix_ventas_tn_metricas_it_transaction', table_name='ventas_tienda_nube_metricas')
    op.drop_table('ventas_tienda_nube_metricas')
