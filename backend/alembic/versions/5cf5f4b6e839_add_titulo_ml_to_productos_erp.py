"""add titulo_ml to productos_erp

Revision ID: 5cf5f4b6e839
Revises: 341fc35260de
Create Date: 2025-10-29 09:17:27.015828

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5cf5f4b6e839'
down_revision: Union[str, None] = '341fc35260de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
