"""ml_publications: un-park the item refresh entries parked by auxiliary-resource errors

Revision ID: 20261021_ml_pub_queue_unpark_items
Revises: 20261020_ml_billing_flex_recompute_trigger
Create Date: 2026-10-21

Data only. From 2026-10-09 (sweeps and promotions enabled) ML answers that are states of the item (performance
"not calculated" for a non-active item, moderation record lists and 204s, promotions "not eligible") were
recorded as errors, so the refresh entries of ~8.5k items reached `ML_PUB_MAX_ATTEMPTS` and parked. A parked
entry is never claimed and absorbed every later notification, so those items stopped updating (status, price).
The parsers now store those answers as states and a `core`/`bundle` trigger supersedes a failure state
(`queue.CORE_TRIGGERS`); this revision puts the entries already parked back in circulation once.

Every parked, unclaimed `item` entry becomes a fresh `bundle` refresh (the item core plus the enabled
sub-resources, each subject to its minimum age), with no attempts, due now, on the backfill lane (3) so the
backlog never delays live notifications (a manual entry keeps lane 0; a later notification lifts it to 1).
Idempotent: a rerun only touches entries parked again since. Downgrade is a no-op: re-parking entries would
freeze the items again, and which ones were parked is still in `last_error`.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261021_ml_pub_queue_unpark_items"
down_revision: Union[str, None] = "20261020_ml_billing_flex_recompute_trigger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNPARK_SQL = """
    UPDATE ml_pub_refresh_queue
    SET parked_at = NULL,
        attempts = 0,
        resources = ARRAY['bundle']::text[],
        not_before = now(),
        lane = CASE WHEN lane = 0 THEN 0 ELSE 3 END,
        version = version + 1
    WHERE kind = 'item' AND parked_at IS NOT NULL AND claimed_at IS NULL
"""


def upgrade() -> None:
    # The refresh workers lock queue rows only briefly (`FOR UPDATE SKIP LOCKED`): wait for them, never stall.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(UNPARK_SQL)


def downgrade() -> None:
    pass
