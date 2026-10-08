"""ml_items: index for the default order of the Publicaciones list (recent activity)

The list orders live items by `last_trigger_received_at DESC NULLS LAST, item_id` and shows the first 50.
Without an index that matches the ORDER BY, Postgres sorts every live item (about 25k, with their
LEFT JOINs) to return one page; with it the first page is an index walk that stops after `LIMIT` rows.
The `WHERE gone_at IS NULL` predicate is the list's own (gone items are hidden by default), which also keeps
the index small.

The expression order must stay identical to `view/listing.py::_order_by`; a test pins that the planner walks
this index for that ORDER BY.

`CREATE INDEX CONCURRENTLY` (outside a transaction, so it never blocks the sweep's writes to `ml_items`) with
a short `lock_timeout` so it gives up instead of queueing behind a long transaction and blocking everything
behind itself. A build that fails midway leaves the index INVALID, and `IF NOT EXISTS` would then skip it: it
is dropped first so the build starts clean.

`SET lock_timeout` is session-level, so (as for every CONCURRENTLY index migration of this repo, e.g.
`20261009_om_dirty_priority_index`) alembic must connect to Postgres directly, not through PgBouncer in
transaction mode, where the SET, the CREATE and the RESET could land on different server connections.

Revision ID: 20261011_ml_items_last_trigger_index
Revises: 20261010_ml_user_product_stock_locations
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_ml_items_last_trigger_index"
down_revision: Union[str, None] = "20261010_ml_user_product_stock_locations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "ix_ml_items_last_trigger"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            invalid = (
                op.get_bind()
                .execute(
                    sa.text(
                        "SELECT NOT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE c.relname = :name AND n.nspname = current_schema()"
                    ),
                    {"name": _INDEX},
                )
                .scalar()
            )
            if invalid:
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
                "ON ml_items (last_trigger_received_at DESC NULLS LAST, item_id) WHERE gone_at IS NULL"
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
