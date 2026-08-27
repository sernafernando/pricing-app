"""merge the two heads left by PR #1199 and PR #1200

Revision ID: 20260826_merge_heads
Revises: 20260824_tn_image_normalizer, 20260826_ml_bot_fallback_reason
Create Date: 2026-08-26

Both branches were cut from `20260821_tn_reconcile_excepcion` and merged to
main independently, so each declared it as its `down_revision`:

  * `20260824_tn_image_normalizer`   (PR #1199, TinyMCE image normalizer)
  * `20260826_ml_bot_fallback_reason` (PR #1200, ml-bot fallback reason)

Neither PR was rebased on the other, so main now has two heads and
`alembic upgrade head` fails with "Multiple head revisions are present".
This revision has no schema effect — it only rejoins the two lineages so a
single `head` exists again. The two migrations touch unrelated tables
(`tn_*` vs `ml_bot_questions`), so their order relative to each other is
irrelevant and no data reconciliation is needed.

Operational note: a deploy stuck on the divergence can be unblocked with
`alembic upgrade heads` (plural) before this lands; afterwards the ordinary
singular `alembic upgrade head` works again.
"""

from typing import Sequence, Union

revision: str = "20260826_merge_heads"
down_revision: Union[str, Sequence[str], None] = (
    "20260824_tn_image_normalizer",
    "20260826_ml_bot_fallback_reason",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No schema change — this revision exists only to rejoin the lineages."""


def downgrade() -> None:
    """No schema change — splitting the lineages again is a no-op."""
