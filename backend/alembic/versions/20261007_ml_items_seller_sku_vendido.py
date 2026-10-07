"""ml_order_items_ops.seller_sku_vendido: the SKU an item was first ingested with

Revision ID: 20261007_ml_items_seller_sku_vendido
Revises: 20261007_ml_publications_quality
Create Date: 2026-10-07

`seller_sku` is overwritten with the CURRENT MercadoLibre value on every
re-ingestion, so the SKU a unit was sold with is lost when the SKU changes
afterwards (e.g. 1214 -> 1215). `seller_sku_vendido` keeps the first known SKU:
ingestion fills it on INSERT and never overwrites it on UPDATE. Ventas ML keeps
showing `seller_sku` (the current one) and shows this one as "ex <SKU>" when it
differs; search matches either.

Backfill: `seller_sku_vendido = seller_sku` for existing rows. What was already
overwritten before this migration cannot be recovered (`raw_item` is overwritten
by the same upsert).

The ALTER is metadata-only (nullable, no default) but needs a brief ACCESS
EXCLUSIVE lock on a table ingestion writes to, hence `lock_timeout`. The
backfill runs in id-range batches so it never holds one long transaction's row
locks against ingestion. `UPDATE OF seller_sku_vendido` does not fire the
order-metrics triggers (they watch quantity/unit_price/full_unit_price/sale_fee).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261007_ml_items_seller_sku_vendido"
down_revision: Union[str, None] = "20261007_ml_publications_quality"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BATCH = 20000


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.add_column("ml_order_items_ops", sa.Column("seller_sku_vendido", sa.String(length=60), nullable=True))
    op.execute("SET LOCAL lock_timeout = DEFAULT")

    bind = op.get_bind()
    max_id = bind.execute(sa.text("SELECT COALESCE(MAX(id), 0) FROM ml_order_items_ops")).scalar() or 0
    for start in range(0, max_id + 1, _BATCH):
        bind.execute(
            sa.text(
                "UPDATE ml_order_items_ops SET seller_sku_vendido = seller_sku "
                "WHERE id >= :lo AND id < :hi AND seller_sku_vendido IS NULL AND seller_sku IS NOT NULL"
            ),
            {"lo": start, "hi": start + _BATCH},
        )

    op.create_index("ix_ml_order_items_ops_seller_sku_vendido", "ml_order_items_ops", ["seller_sku_vendido"])


def downgrade() -> None:
    op.drop_index("ix_ml_order_items_ops_seller_sku_vendido", table_name="ml_order_items_ops")
    op.drop_column("ml_order_items_ops", "seller_sku_vendido")
