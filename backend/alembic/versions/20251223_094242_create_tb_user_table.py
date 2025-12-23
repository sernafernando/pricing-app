"""create_tb_user_table

Revision ID: 20251223_094242
Revises: 
Create Date: 2025-12-23 09:42:42

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251223_094242'
down_revision = 'add_export_activo'  # Depends on export_activo field
branch_labels = None
depends_on = None


def upgrade():
    """
    Crea tabla tb_user para almacenar usuarios del ERP.
    Sincronizada desde tbUser (Export 88) via gbp-parser.
    
    user_name: firstname + lastname o user_nick
    user_loginname: user_nick del ERP  
    user_isactive: user_login=1 AND user_Blocked=0
    """
    op.create_table(
        'tb_user',
        sa.Column('user_id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('user_name', sa.String(200)),  # firstname + lastname
        sa.Column('user_loginname', sa.String(100)),  # user_nick
        sa.Column('user_email', sa.String(200)),
        sa.Column('user_isactive', sa.Boolean, server_default='true'),
        sa.Column('user_lastupdate', sa.DateTime),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Índices
    op.create_index('ix_tb_user_user_id', 'tb_user', ['user_id'])
    op.create_index('ix_tb_user_user_loginname', 'tb_user', ['user_loginname'])
    op.create_index('ix_tb_user_user_isactive', 'tb_user', ['user_isactive'])


def downgrade():
    op.drop_index('ix_tb_user_user_isactive', 'tb_user')
    op.drop_index('ix_tb_user_user_loginname', 'tb_user')
    op.drop_index('ix_tb_user_user_id', 'tb_user')
    op.drop_table('tb_user')
