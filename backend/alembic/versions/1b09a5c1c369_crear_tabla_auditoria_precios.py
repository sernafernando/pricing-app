"""crear_tabla_auditoria_precios

Revision ID: 1b09a5c1c369
Revises: be7e944130f0
Create Date: 2025-10-23 09:55:23.566415

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b09a5c1c369'
down_revision: Union[str, None] = 'be7e944130f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
