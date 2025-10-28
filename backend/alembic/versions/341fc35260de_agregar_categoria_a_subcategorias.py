"""agregar_categoria_a_subcategorias

Revision ID: 341fc35260de
Revises: 1b09a5c1c369
Create Date: 2025-10-27 13:27:04.496029

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '341fc35260de'
down_revision: Union[str, None] = '1b09a5c1c369'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
