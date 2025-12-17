"""Agregar tabla precio_gremio_override y permiso editar_precio_gremio_manual

Revision ID: 20251217_precio_gremio_override
Revises: create_pedido_prep_cache
Create Date: 2025-12-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251217_precio_gremio_override'
down_revision = 'create_pedido_prep_cache'
branch_labels = None
depends_on = None


def upgrade():
    # Crear tabla precio_gremio_override
    op.create_table(
        'precio_gremio_override',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('precio_gremio_sin_iva_manual', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('precio_gremio_con_iva_manual', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id', name='uq_precio_gremio_override_item_id')
    )
    
    # Crear índice
    op.create_index('ix_precio_gremio_override_item_id', 'precio_gremio_override', ['item_id'])
    
    # Foreign keys
    op.create_foreign_key(
        'fk_precio_gremio_override_created_by',
        'precio_gremio_override', 'usuarios',
        ['created_by_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_precio_gremio_override_updated_by',
        'precio_gremio_override', 'usuarios',
        ['updated_by_id'], ['id'],
        ondelete='SET NULL'
    )
    
    # Agregar permiso tienda.editar_precio_gremio_manual
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
        VALUES ('tienda.editar_precio_gremio_manual', 'Editar precio gremio manualmente', 
                'Permite editar manualmente los precios de la lista gremio', 'tienda', 18, false)
        ON CONFLICT (codigo) DO NOTHING;
    """)
    
    # Asignar permiso a roles que ya tienen tienda.editar_precio_gremio
    op.execute("""
        INSERT INTO rol_permisos (rol_id, permiso_id)
        SELECT DISTINCT rp.rol_id, p_new.id
        FROM rol_permisos rp
        JOIN permisos p_old ON rp.permiso_id = p_old.id
        CROSS JOIN permisos p_new
        WHERE p_old.codigo = 'tienda.editar_precio_gremio'
        AND p_new.codigo = 'tienda.editar_precio_gremio_manual'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    # Eliminar permiso
    op.execute("DELETE FROM permisos WHERE codigo = 'tienda.editar_precio_gremio_manual';")
    
    # Eliminar tabla
    op.drop_index('ix_precio_gremio_override_item_id', table_name='precio_gremio_override')
    op.drop_table('precio_gremio_override')
