"""mover activo de productos_erp a publicaciones_ml

Revision ID: b72e99fcc3c8
Revises: d19958be66a1
Create Date: 2025-10-01 11:03:28.626765

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b72e99fcc3c8'
down_revision: Union[str, None] = 'd19958be66a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # ❌ No intentes dropear 'activo' porque nunca existió en DB
    op.add_column(
        'publicaciones_ml',
        sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )


def downgrade():
    op.drop_column('publicaciones_ml', 'activo')
    # si querés, acá podrías re-crear 'activo' en productos_erp
    # op.add_column(
    #     'productos_erp',
    #     sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    # )