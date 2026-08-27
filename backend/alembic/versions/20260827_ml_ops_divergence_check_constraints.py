"""ml-ventas-fuente-de-verdad slice 3: CHECK constraints on ml_ops_divergence
and ml_ops_sync_cursor

Revision ID: 20260827_ml_ops_divergence_check
Revises: 20260826_ml_orders_ops_models
Create Date: 2026-08-27

Slice 1 shipped `ml_ops_divergence.kind`/`state` as plain String columns
whose valid values lived only in a comment, because nothing wrote to them
yet. Slice 3 is the first writer (the out-of-window update counter writes
`kind='out_of_window_update'`), so the contract moves into a real CHECK
constraint here instead of staying disciplinary-only.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260827_ml_ops_divergence_check"
down_revision: Union[str, None] = "20260826_ml_orders_ops_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # These tables are new and nothing writes to them yet, but "nothing
    # writes to them yet" is an assumption, and a CHECK that fails takes
    # the whole deploy down. Anything unexpected is normalised first so
    # the constraint cannot block an upgrade.
    op.execute("UPDATE ml_ops_sync_cursor SET state = 'idle' WHERE state NOT IN ('idle', 'running', 'error')")
    # Normalised, not deleted: the other two statements are UPDATEs that
    # keep the row, and `downgrade()` cannot restore deleted rows anyway.
    # If the "nothing writes here yet" premise held, none of these would be
    # needed; if it does not hold, this is exactly where data would be lost.
    op.execute(
        "UPDATE ml_ops_divergence SET kind = 'unknown' "
        "WHERE kind NOT IN ('missing_in_gbp', 'missing_in_ml', 'field_mismatch', "
        "'out_of_window_update', 'window_not_enumerable')"
    )
    op.execute(
        "UPDATE ml_ops_divergence SET state = 'open' WHERE state NOT IN ('open', 'acknowledged', 'resolved', 'ignored')"
    )
    op.create_check_constraint(
        "ck_ml_ops_sync_cursor_state",
        "ml_ops_sync_cursor",
        "state IN ('idle', 'running', 'error')",
    )
    op.create_check_constraint(
        "ck_ml_ops_divergence_kind",
        "ml_ops_divergence",
        "kind IN ('missing_in_gbp', 'missing_in_ml', 'field_mismatch', 'out_of_window_update', "
        "'window_not_enumerable', 'unknown')",
    )
    op.create_check_constraint(
        "ck_ml_ops_divergence_state",
        "ml_ops_divergence",
        "state IN ('open', 'acknowledged', 'resolved', 'ignored')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ml_ops_sync_cursor_state", "ml_ops_sync_cursor", type_="check")
    op.drop_constraint("ck_ml_ops_divergence_state", "ml_ops_divergence", type_="check")
    op.drop_constraint("ck_ml_ops_divergence_kind", "ml_ops_divergence", type_="check")
