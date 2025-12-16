"""create tienda_config table

Revision ID: g1h2i3j4k5l6
Revises: e8f3c4d5a6b2
Create Date: 2025-12-15 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'g1h2i3j4k5l6'
down_revision = 'e8f3c4d5a6b2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tienda_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clave', sa.String(100), nullable=False),
        sa.Column('valor', sa.Float(), nullable=False, server_default='0'),
        sa.Column('descripcion', sa.String(255), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tienda_config_id'), 'tienda_config', ['id'], unique=False)
    op.create_index(op.f('ix_tienda_config_clave'), 'tienda_config', ['clave'], unique=True)

    # Insertar valor inicial para markup_web_tarjeta
    op.execute("""
        INSERT INTO tienda_config (clave, valor, descripcion)
        VALUES ('markup_web_tarjeta', 0, 'Porcentaje adicional sobre Web Transf para calcular Web Tarjeta')
    """)


def downgrade():
    op.drop_index(op.f('ix_tienda_config_clave'), table_name='tienda_config')
    op.drop_index(op.f('ix_tienda_config_id'), table_name='tienda_config')
    op.drop_table('tienda_config')
