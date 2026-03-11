"""merge tn lowercase and other heads

Revision ID: 0b899b78ef87
Revises: 20250129_tn_lowercase, 4b005188978f
Create Date: 2026-01-29 10:14:38.671281

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b899b78ef87'
down_revision: Union[str, None] = ('20250129_tn_lowercase', '4b005188978f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
