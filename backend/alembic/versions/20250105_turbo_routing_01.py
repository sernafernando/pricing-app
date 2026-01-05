"""add turbo routing tables

Revision ID: 20250105_turbo_routing_01
Revises: 20251226_trigger_01
Create Date: 2025-01-05 12:30:00

Agrega sistema de routing para envíos Turbo de MercadoLibre:
- motoqueros: Repartidores disponibles
- zonas_reparto: Polígonos de zonas CABA (GeoJSON)
- asignaciones_turbo: Asignación de envíos a motoqueros
- geocoding_cache: Cache de direcciones geocodificadas
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250105_turbo_routing_01'
down_revision = '20251226_trigger_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Crear tabla motoqueros
    op.create_table(
        'motoqueros',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(100), nullable=False),
        sa.Column('telefono', sa.String(20), nullable=True),
        sa.Column('activo', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('zona_preferida_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_motoqueros_activo', 'motoqueros', ['activo'], unique=False)

    # Crear tabla zonas_reparto
    op.create_table(
        'zonas_reparto',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(100), nullable=False),
        sa.Column('poligono', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('color', sa.String(7), nullable=False),  # Hex color
        sa.Column('activa', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('creado_por', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['creado_por'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_zonas_reparto_activa', 'zonas_reparto', ['activa'], unique=False)

    # Agregar FK de zona_preferida_id a motoqueros (después de crear zonas_reparto)
    op.create_foreign_key(
        'fk_motoqueros_zona_preferida',
        'motoqueros', 'zonas_reparto',
        ['zona_preferida_id'], ['id'],
        ondelete='SET NULL'
    )

    # Crear tabla asignaciones_turbo
    op.create_table(
        'asignaciones_turbo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mlshippingid', sa.String(50), nullable=False),  # FK a tb_mercadolibre_orders_shipping
        sa.Column('motoquero_id', sa.Integer(), nullable=False),
        sa.Column('zona_id', sa.Integer(), nullable=True),
        sa.Column('direccion', sa.String(500), nullable=False),
        sa.Column('latitud', sa.Numeric(10, 8), nullable=True),
        sa.Column('longitud', sa.Numeric(11, 8), nullable=True),
        sa.Column('orden_ruta', sa.Integer(), nullable=True),  # Orden de entrega optimizado
        sa.Column('estado', sa.String(20), server_default='pendiente', nullable=False),
        sa.Column('asignado_por', sa.String(20), nullable=True),  # 'automatico' o 'manual'
        sa.Column('asignado_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('entregado_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notas', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['motoquero_id'], ['motoqueros.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['zona_id'], ['zonas_reparto.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_asignaciones_mlshippingid', 'asignaciones_turbo', ['mlshippingid'], unique=False)
    op.create_index('idx_asignaciones_motoquero', 'asignaciones_turbo', ['motoquero_id'], unique=False)
    op.create_index('idx_asignaciones_estado', 'asignaciones_turbo', ['estado'], unique=False)
    op.create_index('idx_asignaciones_zona', 'asignaciones_turbo', ['zona_id'], unique=False)

    # Crear tabla geocoding_cache
    op.create_table(
        'geocoding_cache',
        sa.Column('direccion_hash', sa.String(32), nullable=False),  # MD5 de direccion_normalizada
        sa.Column('direccion_normalizada', sa.String(500), nullable=False),
        sa.Column('latitud', sa.Numeric(10, 8), nullable=False),
        sa.Column('longitud', sa.Numeric(11, 8), nullable=False),
        sa.Column('provider', sa.String(20), nullable=True),  # 'google', 'nominatim', etc.
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('direccion_hash')
    )
    op.create_index('idx_geocoding_direccion', 'geocoding_cache', ['direccion_normalizada'], unique=False)

    # Agregar comentarios
    op.execute("COMMENT ON TABLE motoqueros IS 'Repartidores disponibles para envíos Turbo'")
    op.execute("COMMENT ON TABLE zonas_reparto IS 'Polígonos de zonas CABA para asignación de envíos Turbo'")
    op.execute("COMMENT ON TABLE asignaciones_turbo IS 'Asignación de envíos Turbo a motoqueros'")
    op.execute("COMMENT ON TABLE geocoding_cache IS 'Cache de direcciones geocodificadas para evitar llamadas repetidas a APIs'")
    op.execute("COMMENT ON COLUMN zonas_reparto.poligono IS 'GeoJSON del polígono de la zona'")
    op.execute("COMMENT ON COLUMN asignaciones_turbo.estado IS 'Estados: pendiente, en_camino, entregado, cancelado'")


def downgrade() -> None:
    # Eliminar en orden inverso por las FKs
    op.drop_index('idx_geocoding_direccion', table_name='geocoding_cache')
    op.drop_table('geocoding_cache')

    op.drop_index('idx_asignaciones_zona', table_name='asignaciones_turbo')
    op.drop_index('idx_asignaciones_estado', table_name='asignaciones_turbo')
    op.drop_index('idx_asignaciones_motoquero', table_name='asignaciones_turbo')
    op.drop_index('idx_asignaciones_mlshippingid', table_name='asignaciones_turbo')
    op.drop_table('asignaciones_turbo')

    op.drop_index('idx_zonas_reparto_activa', table_name='zonas_reparto')
    op.drop_table('zonas_reparto')

    op.drop_index('idx_motoqueros_activo', table_name='motoqueros')
    op.drop_table('motoqueros')
