"""add mlp_official_store_id to ml_ventas_metricas and tienda_oficial to offset consumo tables

Revision ID: 20250127_tienda_oficial
Revises: 20250126_last_migration
Create Date: 2025-01-27 00:00:00

Agrega mlp_official_store_id a ml_ventas_metricas para poder filtrar rentabilidad por tienda oficial.
Agrega tienda_oficial a offset_grupo_consumo y offset_individual_consumo para calcular offsets correctamente por tienda.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250127_tienda_oficial'
down_revision = 'add_items_sin_mla_permisos'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agregar mlp_official_store_id a ml_ventas_metricas
    op.add_column(
        'ml_ventas_metricas',
        sa.Column('mlp_official_store_id', sa.Integer(), nullable=True)
    )
    
    # Crear índice para mejorar queries filtradas por tienda oficial
    op.create_index(
        'idx_ml_ventas_metricas_official_store',
        'ml_ventas_metricas',
        ['mlp_official_store_id'],
        unique=False
    )
    
    # Agregar tienda_oficial a offset_grupo_consumo
    op.add_column(
        'offset_grupo_consumo',
        sa.Column('tienda_oficial', sa.String(20), nullable=True)
    )
    
    # Crear índice para mejorar queries de consumo por tienda
    op.create_index(
        'idx_offset_grupo_consumo_tienda',
        'offset_grupo_consumo',
        ['grupo_id', 'tienda_oficial'],
        unique=False
    )
    
    # Agregar tienda_oficial a offset_individual_consumo
    op.add_column(
        'offset_individual_consumo',
        sa.Column('tienda_oficial', sa.String(20), nullable=True)
    )
    
    # Crear índice para mejorar queries de consumo individual por tienda
    op.create_index(
        'idx_offset_individual_consumo_tienda',
        'offset_individual_consumo',
        ['offset_id', 'tienda_oficial'],
        unique=False
    )
    
    # Comentarios explicativos
    op.execute(
        "COMMENT ON COLUMN ml_ventas_metricas.mlp_official_store_id IS "
        "'ID de tienda oficial de MercadoLibre (57997=Gauss, 2645=TP-Link, 144=Forza/Verbatim, 191942=Multi-marca)'"
    )
    
    op.execute(
        "COMMENT ON COLUMN offset_grupo_consumo.tienda_oficial IS "
        "'ID de tienda oficial para calcular offsets por tienda (null = todas las tiendas)'"
    )
    
    op.execute(
        "COMMENT ON COLUMN offset_individual_consumo.tienda_oficial IS "
        "'ID de tienda oficial para calcular offsets por tienda (null = todas las tiendas)'"
    )


def downgrade() -> None:
    # Eliminar índices
    op.drop_index('idx_offset_individual_consumo_tienda', table_name='offset_individual_consumo')
    op.drop_index('idx_offset_grupo_consumo_tienda', table_name='offset_grupo_consumo')
    op.drop_index('idx_ml_ventas_metricas_official_store', table_name='ml_ventas_metricas')
    
    # Eliminar columnas
    op.drop_column('offset_individual_consumo', 'tienda_oficial')
    op.drop_column('offset_grupo_consumo', 'tienda_oficial')
    op.drop_column('ml_ventas_metricas', 'mlp_official_store_id')
