"""hay_mejores_excluido on ml_item_seller_promotions (opt-out of hay mejores).

Revision ID: 20261114_hay_mejores_excluido
Revises: 20261114_marcas_visibles_excepciones
Create Date: 2026-11-14

Column only (no new index): excluded rows are few; list filter uses EXISTS on
item_id PK. A partial index can land later if the excluded set grows enough
to need it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261114_hay_mejores_excluido"
down_revision: Union[str, None] = "20261114_marcas_visibles_excepciones"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ml_item_seller_promotions",
        sa.Column("hay_mejores_excluido", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("ml_item_seller_promotions", "hay_mejores_excluido")
