"""merge alertas and tiendanube branches

Revision ID: db78d30e1d6d
Revises: 0b899b78ef87, 38aea5ee4513
Create Date: 2026-02-02 11:44:38.791014

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db78d30e1d6d'
down_revision: Union[str, None] = ('0b899b78ef87', '38aea5ee4513')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
