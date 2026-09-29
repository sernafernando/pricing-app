"""Gross billed + currency on the group metrics record (ventas-ml-rediseno PR20, KPI R18).

A follow-up migration rather than an edit to `20260929_ml_group_metrics`:
that one may already have been applied somewhere, and a migration that has
run is never rewritten -- the next one adds what is missing.

WHY THESE TWO COLUMNS EXIST: KPI aggregation reads ONE row per pedido. The
first cut of the table carried the Gauss chain (neto, costo, total_gauss,
markup) but not the gross billed, so the KPI would still have had to walk a
group's member orders for that single measure -- exactly the query-time
summing this slice removes. Storing it here makes the group record
self-sufficient.

BOTH columns are NULL together, by the rule `listar_ventas` already applies
to a pack row: a group whose members do not share one currency, or any of
whose amounts is unknown, has NO gross amount. Adding ARS to USD produces a
number that means nothing, and an amount without its currency is the
misleading value the gate exists to prevent.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_ml_group_metrics_gross_amount"
down_revision: Union[str, None] = "20260929_ml_group_metrics_pack_fanout"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_group_metrics", sa.Column("gross_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("ml_group_metrics", sa.Column("currency_id", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("ml_group_metrics", "currency_id")
    op.drop_column("ml_group_metrics", "gross_amount")
