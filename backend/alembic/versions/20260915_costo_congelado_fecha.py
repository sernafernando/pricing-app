"""ml_order_item_costos: add costo_fecha (the cost's own date)

Revision ID: 20260915_costo_fecha
Revises: 20260915_raw_costs
Create Date: 2026-09-15

Adds `costo_fecha` (Date, nullable) to `ml_order_item_costos`: the date the
`costo_origen` we froze is attributable to.

NULLABLE ON PURPOSE, not a gap to close later: a row frozen by the LIVE path
(`costeo_service.congelar`) reads the CURRENT `ProductoERP.costo`, which
carries no date of its own -- `congelado_at` already records WHEN we read
it, but not what date the cost value itself belongs to. Those rows stay
NULL forever.

A row written by the backfill script
(`app/scripts/backfill_costo_congelado.py`) DOES have a real answer: it
resolved `costo_origen` from a specific `ItemCostListHistory` row, dated at
or before the sale, and this column gets that row's `iclh_cd`.

Why this exists: without it, a live-frozen row and a backfilled row are
byte-identical except for `fuente` (see the backfill's
`FUENTE_BACKFILL_PUBLICACION`/`FUENTE_BACKFILL_SKU` constants). If a
backfilled cost is later found to be wrong -- the wrong history row, or a
window that should not have been eligible -- `costo_fecha` lets a
correction target EXACTLY the rows that came from a given dated cost,
instead of re-deriving that from `fuente` plus a join back to history that
may no longer resolve the same way.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_costo_fecha"
down_revision: Union[str, None] = "20260915_raw_costs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ml_order_item_costos",
        sa.Column(
            "costo_fecha",
            sa.Date(),
            nullable=True,
            comment=(
                "Date the frozen costo_origen is attributable to. NULL for "
                "rows frozen by the live path (no dated source -- read "
                "current ProductoERP.costo). Set to the ItemCostListHistory "
                "row's iclh_cd for rows written by the backfill script, so a "
                "future correction can target exactly those rows."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("ml_order_item_costos", "costo_fecha")
