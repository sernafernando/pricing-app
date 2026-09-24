"""ml_ops_divergence: add stored_metrics_mismatch kind (ventas-ml-rediseno PR6)

Revision ID: 20260924_stored_metrics_mismatch
Revises: 20260923_ml_order_metrics_triggers_config
Create Date: 2026-09-24

Design D10: `order_metrics.divergence` opens `ml_ops_divergence` records
with `kind='stored_metrics_mismatch'` (reusing the existing table, per the
design's explicit "reuse existing table, models ml_orders_ops.py:463"
instruction) whenever a stored `ml_order_metrics` row disagrees with a
fresh `compute_order_metrics` recompute. The CHECK constraint's value list
must widen to admit this new kind BEFORE the divergence handler can ever
insert a row -- migration lands ahead of the handler in this same PR.

Never edits the PR4/PR5 migrations (immutability): this is new DDL in its
own revision, dropping the old constraint and recreating it with the wider
list, same shape as `20260827_ml_ops_divergence_check_constraints.py`
(which this revision does not touch).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260924_stored_metrics_mismatch"
down_revision: Union[str, None] = "20260923_ml_order_metrics_triggers_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_KINDS = (
    "missing_in_gbp",
    "missing_in_ml",
    "field_mismatch",
    "out_of_window_update",
    "window_not_enumerable",
    "unknown",
    "ingest_failed",
)
_NEW_KINDS = _OLD_KINDS + ("stored_metrics_mismatch",)


def upgrade() -> None:
    op.drop_constraint("ck_ml_ops_divergence_kind", "ml_ops_divergence", type_="check")
    op.create_check_constraint(
        "ck_ml_ops_divergence_kind",
        "ml_ops_divergence",
        f"kind IN ({', '.join(repr(k) for k in _NEW_KINDS)})",
    )


def downgrade() -> None:
    # Normalise first, same discipline as the original constraint migration:
    # a downgrade that immediately fails its own CHECK creation takes the
    # rollback down with it. Any `stored_metrics_mismatch` row is
    # re-labelled `unknown` rather than deleted.
    op.execute("UPDATE ml_ops_divergence SET kind = 'unknown' WHERE kind = 'stored_metrics_mismatch'")
    op.drop_constraint("ck_ml_ops_divergence_kind", "ml_ops_divergence", type_="check")
    op.create_check_constraint(
        "ck_ml_ops_divergence_kind",
        "ml_ops_divergence",
        f"kind IN ({', '.join(repr(k) for k in _OLD_KINDS)})",
    )
