"""add fecha_cerrada to alertas_usuarios_estado

Revision ID: df027d1b05df
Revises: 20260317_doc_templates
Create Date: 2026-03-17 14:58:11.875040

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'df027d1b05df'
down_revision: Union[str, None] = '20260317_doc_templates'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'alertas_usuarios_estado',
        sa.Column('fecha_cerrada', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('alertas_usuarios_estado', 'fecha_cerrada')
