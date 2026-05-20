"""merge heads compras + mainline

Revision ID: merge_heads_20260520
Revises: 20260513_add_item_expser, compras_030_nc_local_tipo
Create Date: 2026-05-20 17:13:58.775206

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "merge_heads_20260520"
down_revision: Union[str, None] = ("20260513_add_item_expser", "compras_030_nc_local_tipo")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
