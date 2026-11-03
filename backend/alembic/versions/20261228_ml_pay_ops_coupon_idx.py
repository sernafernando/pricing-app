"""ix_ml_payments_ops_coupon_order_id: partial index for the per-sale discounts pending query (ml-ads-cupones-display T3a)

Revision ID: 20261228_ml_pay_ops_coupon_idx
Revises: 20261228_ml_order_discounts
Create Date: 2026-11-02

The pending query of the discounts ingestion reads only the payments with a coupon: a partial index on
`ml_payments_ops (order_id) WHERE coupon_amount > 0`. Same pattern as 20261011_ml_items_last_trigger_index:

- CONCURRENTLY, because `ml_payments_ops` keeps receiving writes and a plain CREATE INDEX would block them for
  the whole build. It cannot run inside a transaction, hence `autocommit_block()`, and it lives in its own
  revision: `autocommit_block()` commits what the upgrade ran before it, so a failed build next to the tables
  would leave them committed and their revision unrerunnable.
- `lock_timeout`, so a build waiting behind a long write transaction fails in seconds instead of holding the
  deploy; a rerun builds it again.
- A cancelled or failed CONCURRENTLY build leaves an INVALID index with this name, which IF NOT EXISTS alone
  would accept: an invalid leftover is dropped first.

Alembic must connect directly (DATABASE_URL_DIRECT), not through PgBouncer in transaction mode. No data changes;
downgrade drops exactly this index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261228_ml_pay_ops_coupon_idx"
down_revision: Union[str, None] = "20261228_ml_order_discounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "ix_ml_payments_ops_coupon_order_id"


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
                "ON ml_payments_ops (order_id) WHERE coupon_amount > 0"
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
