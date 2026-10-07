"""order_metrics: priority index for the dirty-queue claim.

`claim_dirty` now orders by tier (live work before the `reconcile` /
`divergence` sweeps) and then by `enqueued_at`. Without an index matching
that ORDER BY, Postgres sorts the whole queue on every claim: measured with
80k queued rows, 45 ms and a spill to disk per claim, against 0.1 ms for the
old FIFO order on `ix_ml_order_metrics_dirty_enqueued_at`. With this index
the claim is an index scan again (0.3 ms).

The expression must stay identical to `app.services.order_metrics.queue
._TIER_SQL`; a test pins that the claim uses this index.

`CREATE INDEX CONCURRENTLY` (outside a transaction, so it never blocks the
live trigger writes) with a short `lock_timeout` so it gives up instead of
queueing behind a long transaction and blocking everything behind itself.

Revision ID: 20261009_om_dirty_priority_index
Revises: 20261008_ml_shipments_raw_costs_trigger
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261009_om_dirty_priority_index"
down_revision: Union[str, None] = "20261008_ml_shipments_raw_costs_trigger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "ix_ml_order_metrics_dirty_priority"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
                "ON ml_order_metrics_dirty ((reason IN ('divergence', 'reconcile')), enqueued_at)"
            )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        finally:
            op.execute("RESET lock_timeout")
