"""add auditoria general table

Revision ID: c559fbb7edc8
Revises: 5cf5f4b6e839
Create Date: 2025-10-30 08:13:32.278152

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c559fbb7edc8'
down_revision: Union[str, None] = '5cf5f4b6e839'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
