"""merge alembic heads: promos permisos + ml_bot_messages + index_mlo_cd

The repository accumulated three divergent Alembic heads:
  - 20260710_add_index_mlo_cd    (from 20260708_ml_bot_roster)
  - 20260710_ml_bot_messages     (from 20260708_ml_bot_roster)
  - 20260713_permisos_promociones (from 20260701_deposito_msg)

This is a no-op merge revision that unifies them into a single head so
`alembic upgrade head` works again. It performs no schema changes.

Revision ID: 20260713_merge_heads
Revises: 20260710_add_index_mlo_cd, 20260710_ml_bot_messages, 20260713_permisos_promociones
Create Date: 2026-07-13
"""

from typing import Sequence, Union

revision: str = "20260713_merge_heads"
down_revision: Union[str, Sequence[str], None] = (
    "20260710_add_index_mlo_cd",
    "20260710_ml_bot_messages",
    "20260713_permisos_promociones",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: this revision only merges divergent heads."""
    pass


def downgrade() -> None:
    """No-op: reverting a merge splits back into the prior heads."""
    pass
