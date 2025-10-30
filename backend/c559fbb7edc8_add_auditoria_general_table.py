from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    op.create_table(
        'auditoria',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('tipo_accion', sa.String(50), nullable=False),
        sa.Column('valores_anteriores', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('valores_nuevos', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('es_masivo', sa.Boolean(), server_default='false'),
        sa.Column('productos_afectados', sa.Integer(), nullable=True),
        sa.Column('comentario', sa.String(500), nullable=True),
        sa.Column('fecha', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'])
    )
    op.create_index('ix_auditoria_item_id', 'auditoria', ['item_id'])
    op.create_index('ix_auditoria_tipo_accion', 'auditoria', ['tipo_accion'])
    op.create_index('ix_auditoria_fecha', 'auditoria', ['fecha'])

def downgrade():
    op.drop_index('ix_auditoria_fecha')
    op.drop_index('ix_auditoria_tipo_accion')
    op.drop_index('ix_auditoria_item_id')
    op.drop_table('auditoria')
