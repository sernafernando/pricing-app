def upgrade():
    op.add_column('productos_erp', sa.Column('titulo_ml', sa.String(500), nullable=True))

def downgrade():
    op.drop_column('productos_erp', 'titulo_ml')
