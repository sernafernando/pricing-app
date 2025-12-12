"""Create ventas_fuera_ml_metricas table

Revision ID: ventas_fuera_ml_metricas
Revises: create_tb_state
Create Date: 2025-12-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ventas_fuera_ml_metricas'
down_revision: Union[str, None] = 'create_tb_state'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('ventas_fuera_ml_metricas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('it_transaction', sa.BigInteger(), nullable=False, unique=True, index=True),
        sa.Column('ct_transaction', sa.BigInteger(), index=True),
        sa.Column('item_id', sa.Integer(), index=True),
        sa.Column('codigo', sa.String(100)),
        sa.Column('descripcion', sa.Text()),
        sa.Column('marca', sa.String(255), index=True),
        sa.Column('categoria', sa.String(255), index=True),
        sa.Column('subcategoria', sa.String(255)),
        sa.Column('bra_id', sa.Integer(), index=True),
        sa.Column('sucursal', sa.String(255), index=True),
        sa.Column('sm_id', sa.Integer(), index=True),
        sa.Column('vendedor', sa.String(255), index=True),
        sa.Column('cust_id', sa.Integer(), index=True),
        sa.Column('cliente', sa.String(255)),
        sa.Column('df_id', sa.Integer()),
        sa.Column('tipo_comprobante', sa.String(100)),
        sa.Column('numero_comprobante', sa.String(50)),
        sa.Column('fecha_venta', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('fecha_calculo', sa.Date(), index=True),
        sa.Column('sd_id', sa.Integer()),
        sa.Column('signo', sa.Integer()),
        sa.Column('cantidad', sa.Numeric(18, 4), nullable=False),
        sa.Column('monto_unitario', sa.Numeric(18, 2)),
        sa.Column('monto_total', sa.Numeric(18, 2), nullable=False),
        sa.Column('iva_porcentaje', sa.Numeric(5, 2)),
        sa.Column('monto_iva', sa.Numeric(18, 2)),
        sa.Column('monto_con_iva', sa.Numeric(18, 2)),
        sa.Column('costo_unitario', sa.Numeric(18, 6)),
        sa.Column('costo_total', sa.Numeric(18, 2)),
        sa.Column('moneda_costo', sa.String(10)),
        sa.Column('cotizacion_dolar', sa.Numeric(10, 4)),
        sa.Column('ganancia', sa.Numeric(18, 2)),
        sa.Column('markup_porcentaje', sa.Numeric(10, 2)),
        sa.Column('es_combo', sa.Boolean(), default=False),
        sa.Column('combo_group_id', sa.BigInteger(), index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('ventas_fuera_ml_metricas')
