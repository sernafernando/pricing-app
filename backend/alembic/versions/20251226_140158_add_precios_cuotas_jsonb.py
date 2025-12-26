"""add precios cuotas jsonb

Revision ID: 20251226_cuotas_01
Revises: 20251226_recalc_01
Create Date: 2025-12-26 14:01:58

Agrega campo JSONB para almacenar precios de cuotas calculados automáticamente.

Estructura del JSON:
{
    "adicional_markup": 4.0,
    "cuotas": [
        {
            "cuotas": 3,
            "pricelist_id": 17,
            "precio": 89500.50,
            "comision_base_pct": 17.0,
            "comision_total": 2300.00,
            "limpio": 65000.00,
            "markup_real": 15.02
        },
        ... (6, 9, 12 cuotas)
    ]
}
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251226_cuotas_01'
down_revision = '20251226_recalc_01'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar columna JSONB para precios de cuotas
    op.add_column(
        'calculos_pricing',
        sa.Column('precios_cuotas', postgresql.JSONB, nullable=True)
    )
    
    # Índice GIN para búsquedas rápidas en el JSON (opcional pero útil)
    op.create_index(
        'ix_calculos_pricing_precios_cuotas',
        'calculos_pricing',
        ['precios_cuotas'],
        postgresql_using='gin',
        postgresql_ops={'precios_cuotas': 'jsonb_path_ops'}
    )
    
    print("✅ Campo precios_cuotas (JSONB) agregado a calculos_pricing")


def downgrade():
    op.drop_index('ix_calculos_pricing_precios_cuotas', table_name='calculos_pricing')
    op.drop_column('calculos_pricing', 'precios_cuotas')
