"""add username to usuarios

Revision ID: add_username_usuarios
Revises: merge_heads_20251222
Create Date: 2025-12-22

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_username_usuarios'
down_revision = 'merge_heads_20251222'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Agregar columna username (nullable temporalmente)
    op.add_column('usuarios', sa.Column('username', sa.String(length=100), nullable=True))
    
    # 2. Generar usernames automáticos desde emails para usuarios existentes
    # Extraer la parte antes del @ del email
    op.execute("""
        UPDATE usuarios 
        SET username = LOWER(SPLIT_PART(email, '@', 1))
        WHERE username IS NULL;
    """)
    
    # 3. Manejar duplicados agregando sufijo numérico
    op.execute("""
        WITH ranked_users AS (
            SELECT 
                id,
                username,
                ROW_NUMBER() OVER (PARTITION BY username ORDER BY id) as rn
            FROM usuarios
        )
        UPDATE usuarios u
        SET username = CONCAT(ru.username, '_', ru.rn)
        FROM ranked_users ru
        WHERE u.id = ru.id AND ru.rn > 1;
    """)
    
    # 4. Crear índice único en username
    op.create_index(op.f('ix_usuarios_username'), 'usuarios', ['username'], unique=True)
    
    # 5. Hacer username NOT NULL después de poblar datos
    op.alter_column('usuarios', 'username', nullable=False)
    
    # 6. Hacer email nullable (ya no es obligatorio)
    op.alter_column('usuarios', 'email', nullable=True)


def downgrade() -> None:
    # Revertir cambios
    op.alter_column('usuarios', 'email', nullable=False)
    op.drop_index(op.f('ix_usuarios_username'), table_name='usuarios')
    op.drop_column('usuarios', 'username')
