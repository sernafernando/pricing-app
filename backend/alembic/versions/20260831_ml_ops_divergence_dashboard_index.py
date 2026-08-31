"""ml-ventas-fuente-de-verdad: composite index for the divergence dashboard

Revision ID: 20260831_ml_ops_div_idx
Revises: 20260828_ml_op_links_perms
Create Date: 2026-08-31

`routers/ml_ventas_ops.py`'s divergence endpoints filter on `kind` and/or
`state` and order by `detected_at DESC` -- none of the three was indexed
(only `id`/`order_id`), a guaranteed sequential scan on a table with
unbounded growth (pre-push review, divergence dashboard API).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260831_ml_ops_div_idx"
down_revision: Union[str, None] = "20260828_ml_op_links_perms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_ml_ops_divergence_kind_state_detected_at",
        "ml_ops_divergence",
        ["kind", "state", "detected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ml_ops_divergence_kind_state_detected_at", table_name="ml_ops_divergence")
