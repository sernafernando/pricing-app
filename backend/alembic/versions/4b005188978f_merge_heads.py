"""merge heads

Revision ID: 4b005188978f
Revises: 20250129_sale_order_times, 20260128_rename_isactive
Create Date: 2026-01-29 09:36:33.085948

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b005188978f'
down_revision: Union[str, None] = ('20250129_sale_order_times', '20260128_rename_isactive')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
