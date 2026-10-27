"""ml_shipments_ops.cost_sync_attempts: the cost-sync give-up counter moves off ml_ops_divergence

Revision ID: 20261204_ml_cost_sync_give_up_column
Revises: 20261203_etiquetas_logistica_historial
Create Date: 2026-10-27

remove-ml-divergences D2. The payments/costs backfill counted, per shipment, the runs that fetched its costs
without settling them, and gave up at 5. It kept that counter in the legacy `ml_ops_divergence` table (rows
`order_id=0`, `kind='unknown'`, `field='cost_sync:<shipment_id>'`, the count as text in `ml_value`), read back
through a `NOT IN (...)` of every given-up shipment. Now it is a column on the shipment itself and the candidate
query filters on it.

The existing counters are copied over (Postgres), so a shipment that already gave up stays given up and one halfway
through its attempts keeps its count; values are clamped at 5 like the code does. The legacy rows are left in place:
the table is dropped by a later revision. Downgrade copies the counters back and drops the column.

LOCK NOTE: ADD COLUMN with a constant default is a catalog-only change in Postgres 11+ (no rewrite), but it takes an
ACCESS EXCLUSIVE lock on `ml_shipments_ops`. Behind an open writer it would queue and block every new reader, so
upgrade and downgrade run with `lock_timeout = '5s'` and fail fast (55P03) instead; the deploy is retried. The
transaction-local setting is restored afterwards because `env.py` runs every pending revision in one transaction.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261204_ml_cost_sync_give_up_column"
down_revision: Union[str, None] = "20261203_etiquetas_logistica_historial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_shipments_ops"
COLUMN = "cost_sync_attempts"
MAX_ATTEMPTS = 5  # backfill_payments_costs_service.MAX_COST_SYNC_ATTEMPTS, frozen here
LOCK_TIMEOUT = "5s"

COPY_FROM_DIVERGENCE = f"""
UPDATE {TABLE} s
SET {COLUMN} = LEAST(d.ml_value::integer, {MAX_ATTEMPTS})
FROM ml_ops_divergence d
WHERE d.order_id = 0
  AND d.kind = 'unknown'
  AND d.field ~ '^cost_sync:[0-9]{{1,18}}$'
  AND d.ml_value ~ '^[0-9]{{1,4}}$'
  AND s.shipment_id = substr(d.field, 11)::bigint
"""

COPY_TO_DIVERGENCE = f"""
INSERT INTO ml_ops_divergence (order_id, kind, field, ml_value, detected_at)
SELECT 0, 'unknown', 'cost_sync:' || s.shipment_id, s.{COLUMN}::text, now()
FROM {TABLE} s
WHERE s.{COLUMN} > 0
ON CONFLICT (order_id, kind, field) DO UPDATE SET ml_value = EXCLUDED.ml_value
"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _set_lock_timeout() -> None:
    op.execute("SELECT set_config('ml_cost_sync.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")


def _restore_lock_timeout() -> None:
    op.execute("SELECT set_config('lock_timeout', current_setting('ml_cost_sync.lock_timeout_previo'), true)")


def upgrade() -> None:
    postgres = _is_postgres()
    if postgres:
        _set_lock_timeout()
    op.add_column(TABLE, sa.Column(COLUMN, sa.SmallInteger(), nullable=False, server_default="0"))
    if postgres:
        op.execute(COPY_FROM_DIVERGENCE)
        _restore_lock_timeout()


def downgrade() -> None:
    postgres = _is_postgres()
    if postgres:
        _set_lock_timeout()
        op.execute(COPY_TO_DIVERGENCE)
    op.drop_column(TABLE, COLUMN)
    if postgres:
        _restore_lock_timeout()
