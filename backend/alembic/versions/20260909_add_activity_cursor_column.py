"""Add activity_cursor column to ml_ops_sync_cursor (ml-activity-receiver
slice 2)

Additive, nullable column on `ml_ops_sync_cursor` to hold the opaque
bridge cursor for the future `ml_activity` row (`GET
/api/ml/activity?since=...`). This slice does not seed an `ml_activity`
row and nothing reads or writes this column yet -- the drain that will
use it lands in slice 3. `NULL` means "never drained".

Deliberately not folded into `detail`: `release_lock_as_idle`
(sweep_service.py:1012-1029) clears `detail` to `None` after a completed
pass and overwrites it with a truncation marker after an incomplete one,
so a cursor stored there would be lost on the very next successful drain.

Revision ID: 20260909_activity_cursor
Revises: 20260909_seed_ml_bridge
Create Date: 2026-09-09
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260909_activity_cursor"
down_revision = "20260909_seed_ml_bridge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ml_ops_sync_cursor", sa.Column("activity_cursor", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ml_ops_sync_cursor", "activity_cursor")
