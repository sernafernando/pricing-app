"""Merge heads: ml-ventas-fuente-de-verdad slice 3 and ml-bot-panel-operador PR6

Revision ID: 20260828_merge_ops_panel
Revises: 20260827_ml_ops_divergence_check, 20260827_ml_bot_messages_sent_at
Create Date: 2026-08-28

Two independent, unrelated PRs both branched off `20260826_ml_orders_ops_models`
(this chain's slice 3, and the separately-merged ml-bot-panel-operador PR6),
leaving two heads on `main`. Alembic convention: a merge revision carries no
schema work of its own, so it can be reverted independently of either side's
migrations. Slice 4's own schema work lives in the next revision, on top of
this merge.
"""

from typing import Sequence, Union

revision: str = "20260828_merge_ops_panel"
down_revision: Union[str, tuple[str, ...], None] = (
    "20260827_ml_ops_divergence_check",
    "20260827_ml_bot_messages_sent_at",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
