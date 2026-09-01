"""ml-ventas-listado: payment_status + covered_by_marketplace on ml_orders_ops

Revision ID: 20260901_ml_ops_pay_status
Revises: 20260831_ml_ops_div_idx
Create Date: 2026-09-01

Two new facts on `ml_orders_ops`. Both exist to tell apart sales that the
order's own status alone reports identically:

- `payment_status`: the order's first payment status (`payments[0].status`
  in the raw ML payload). `in_mediation` is the value that matters -- see
  below for why this needs its own
  column instead of a JSONB reach-in at query time. CHECK-constrained to
  Mercado Pago's documented payment status values
  (`app/models/ml_orders_ops.py::PAYMENT_STATUSES`); NULL passes the CHECK
  (SQL: NULL is never "false" under IN), so existing rows with no payment are
  unaffected.
- `covered_by_marketplace`: whether ML's Buyer Protection Programme itself
  refunded a cancelled order's buyer. This ingestion slice could not
  verify where this fact appears in the order payload, so it ships as a
  plain nullable boolean with NO writer yet (every row stays NULL) rather
  than guessing a rule from an unverified field/tag.

Both columns are additive and nullable -- no backfill, no row deleted or
rewritten to satisfy either constraint.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_ml_ops_pay_status"
down_revision: Union[str, None] = "20260831_ml_ops_div_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PAYMENT_STATUSES = (
    "approved",
    "pending",
    "authorized",
    "in_process",
    "in_mediation",
    "rejected",
    "cancelled",
    "refunded",
    "charged_back",
)


def upgrade() -> None:
    op.add_column("ml_orders_ops", sa.Column("payment_status", sa.String(length=20), nullable=True))
    op.add_column("ml_orders_ops", sa.Column("covered_by_marketplace", sa.Boolean(), nullable=True))
    # CONCURRENTLY, following the precedent in
    # `20260710_add_index_mlo_cd_orders_header.py`: a plain CREATE INDEX
    # takes a ShareLock and blocks the sweep's writes for as long as it
    # builds, on a table designed to grow without bound. It cannot run
    # inside a transaction, hence the autocommit block.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ml_orders_ops_payment_status ON ml_orders_ops (payment_status)"
        )
    # NOT VALID first, then VALIDATE. `ADD CONSTRAINT ... CHECK` on its own
    # takes ACCESS EXCLUSIVE and scans the whole table -- a stronger lock
    # than the ShareLock the CONCURRENTLY index above exists to avoid, which
    # would have made that care pointless. NOT VALID takes the lock only
    # briefly and skips the scan; VALIDATE then takes just SHARE UPDATE
    # EXCLUSIVE. Every existing row is NULL, so validation passes.
    allowed = ", ".join(f"'{v}'" for v in _PAYMENT_STATUSES)
    op.execute(
        "ALTER TABLE ml_orders_ops ADD CONSTRAINT ck_ml_orders_ops_payment_status "
        f"CHECK (payment_status IN ({allowed})) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute("ALTER TABLE ml_orders_ops VALIDATE CONSTRAINT ck_ml_orders_ops_payment_status")


def downgrade() -> None:
    op.drop_constraint("ck_ml_orders_ops_payment_status", "ml_orders_ops", type_="check")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_ml_orders_ops_payment_status")
    op.drop_column("ml_orders_ops", "covered_by_marketplace")
    op.drop_column("ml_orders_ops", "payment_status")
