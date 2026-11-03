"""hay_mejores_ofertas on ml_item_seller_promotions (+ fingerprints, partial index).

Revision ID: 20261102_hay_mejores_ofertas
Revises: 20261230_rma_borrar_revisado
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261102_hay_mejores_ofertas"
down_revision: Union[str, None] = "20261230_rma_borrar_revisado"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ml_item_seller_promotions",
        sa.Column("hay_mejores_ofertas", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("ml_item_seller_promotions", sa.Column("hay_mejores_fingerprint", sa.Text(), nullable=True))
    op.add_column(
        "ml_item_seller_promotions",
        sa.Column("hay_mejores_descartado_fingerprint", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_ml_item_seller_promotions_hay_mejores",
        "ml_item_seller_promotions",
        ["item_id"],
        unique=False,
        postgresql_where=sa.text("hay_mejores_ofertas = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_ml_item_seller_promotions_hay_mejores", table_name="ml_item_seller_promotions")
    op.drop_column("ml_item_seller_promotions", "hay_mejores_descartado_fingerprint")
    op.drop_column("ml_item_seller_promotions", "hay_mejores_fingerprint")
    op.drop_column("ml_item_seller_promotions", "hay_mejores_ofertas")
