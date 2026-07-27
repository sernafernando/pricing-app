"""Create offset_individual_consumo and offset_individual_resumen tables

Revision ID: offset_indiv_consumo
Revises: offset_grupo_consumo
Create Date: 2025-12-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'offset_indiv_consumo'
down_revision: Union[str, None] = 'offset_grupo_consumo'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tabla para registrar cada consumo individual de un offset (sin grupo)
    op.create_table('offset_individual_consumo',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('offset_id', sa.Integer(), sa.ForeignKey('offsets_ganancia.id'), nullable=False, index=True),
        sa.Column('id_operacion', sa.BigInteger(), index=True),  # Para ventas ML
        sa.Column('venta_fuera_id', sa.Integer(), index=True),  # Para ventas fuera ML
        sa.Column('tipo_venta', sa.String(20), nullable=False),  # 'ml' o 'fuera_ml'
        sa.Column('fecha_venta', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('item_id', sa.Integer(), index=True),
        sa.Column('cantidad', sa.Integer(), nullable=False),
        sa.Column('monto_offset_aplicado', sa.Numeric(18, 2), nullable=False),  # En ARS
        sa.Column('monto_offset_usd', sa.Numeric(18, 2)),  # En USD
        sa.Column('cotizacion_dolar', sa.Numeric(10, 4)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Tabla resumen por offset individual (para consultas rápidas)
    op.create_table('offset_individual_resumen',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('offset_id', sa.Integer(), sa.ForeignKey('offsets_ganancia.id'), unique=True, nullable=False, index=True),
        sa.Column('total_unidades', sa.Integer(), default=0),
        sa.Column('total_monto_ars', sa.Numeric(18, 2), default=0),
        sa.Column('total_monto_usd', sa.Numeric(18, 2), default=0),
        sa.Column('cantidad_ventas', sa.Integer(), default=0),
        sa.Column('limite_alcanzado', sa.String(20)),  # 'unidades', 'monto', None
        sa.Column('fecha_limite_alcanzado', sa.DateTime(timezone=True)),
        sa.Column('ultima_venta_fecha', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('offset_individual_resumen')
    op.drop_table('offset_individual_consumo')
