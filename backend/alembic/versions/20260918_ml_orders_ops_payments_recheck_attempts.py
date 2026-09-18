"""ml_orders_ops.payments_recheck_attempts

Counts how many times the deferred payment re-ask has actually been
attempted for an order, so the retry can be bounded by ATTEMPTS instead
of by the order's age.

Why a column and not a derived value: nothing already on the row can
answer "how long has this re-ask been going". `date_created` is the
ORDER's age, which says nothing about when the recheck was scheduled --
an order that is already older than the cutoff when its first recheck
comes due would be abandoned on attempt number one, with zero retries.
`payments_synced_at` is overwritten on every reseal. `payments_recheck_at`
is always rewritten as `now + RECHECK_AFTER` and so carries no history at
all. Bounding the retry on any of those means a field that says one thing
and measures another.

Revision ID: 20260918_payments_recheck_attempts
Revises: 20260918_payments_recheck_at
"""

from alembic import op
import sqlalchemy as sa

revision = "20260918_payments_recheck_attempts"
down_revision = "20260918_payments_recheck_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOT NULL with a server_default: existing rows get 0 without a
    # backfill pass, and a row inserted by code that predates this column
    # still lands valid rather than failing the insert.
    op.add_column(
        "ml_orders_ops",
        sa.Column("payments_recheck_attempts", sa.SmallInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("ml_orders_ops", "payments_recheck_attempts")
