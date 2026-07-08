"""ml-bot: add llm_provider column to ml_bot_questions

Revision ID: 20260707_ml_bot_prov
Revises: 20260707_ml_bot_item
Create Date: 2026-07-07

PR de pulido item #2 (see engram sdd/ml-questions-ai/polish-pr): track which
provider/model produced each bot draft (e.g. "groq/llama-3.3-70b-versatile"),
for observability and to explain answer quality variance in the panel's
expanded detail view.

Additive and reversible: nullable column, no backfill, no data loss on
downgrade.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260707_ml_bot_prov"
down_revision: Union[str, None] = "20260707_ml_bot_item"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_bot_questions", sa.Column("llm_provider", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("ml_bot_questions", "llm_provider")
