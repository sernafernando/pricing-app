"""create markups_tienda_brand table

Revision ID: 20251212_144425
Revises: 20251212_143711
Create Date: 2025-12-12 14:44:25

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251212_144425'
down_revision = '20251212_143711'
branch_labels = None
depends_on = None


def upgrade():
    """Crear tabla para markups de tienda por marca"""

    op.create_table(
        'markups_tienda_brand',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('comp_id', sa.Integer(), nullable=False),
        sa.Column('brand_id', sa.Integer(), nullable=False),
        sa.Column('brand_desc', sa.String(255), nullable=True),
        sa.Column('markup_porcentaje', sa.Float(), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('notas', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by_id'], ['usuarios.id'], ),
        sa.ForeignKeyConstraint(['updated_by_id'], ['usuarios.id'], )
    )

    # Índices
    op.create_index('ix_markups_tienda_brand_id', 'markups_tienda_brand', ['id'])
    op.create_index('ix_markups_tienda_brand_brand_id', 'markups_tienda_brand', ['brand_id'])
    op.create_index('ix_markups_tienda_brand_comp_brand', 'markups_tienda_brand', ['comp_id', 'brand_id'], unique=True)


def downgrade():
    """Eliminar tabla de markups de tienda por marca"""

    op.drop_index('ix_markups_tienda_brand_comp_brand', table_name='markups_tienda_brand')
    op.drop_index('ix_markups_tienda_brand_brand_id', table_name='markups_tienda_brand')
    op.drop_index('ix_markups_tienda_brand_id', table_name='markups_tienda_brand')
    op.drop_table('markups_tienda_brand')
