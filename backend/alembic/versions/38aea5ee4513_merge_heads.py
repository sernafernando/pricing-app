"""merge heads

Revision ID: 38aea5ee4513
Revises: 20251212_141908, create_tb_item_association
Create Date: 2025-12-12 14:20:29.395999

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '38aea5ee4513'
down_revision: Union[str, None] = ('20251212_141908', 'create_tb_item_association')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
