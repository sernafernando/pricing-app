"""ml-bot: add item_title/item_permalink enrichment columns to ml_bot_questions

Revision ID: 20260707_ml_bot_item
Revises: 20260706_ml_bot
Create Date: 2026-07-07

Panel v2 requirement #2 (see engram sdd/ml-questions-ai/panel-v2): the panel
needs to show WHICH product a question is about (title + link into ML).
Both columns are nullable — ingestion enrichment (ml_client.get_item) is
best-effort and must never block ingestion (see ingestion_service.py), so
existing/failed rows legitimately have NULL here; the frontend falls back to
a link built from item_id.

Additive and reversible: no backfill, no data loss on downgrade.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260707_ml_bot_item"
down_revision: Union[str, None] = "20260706_ml_bot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_bot_questions", sa.Column("item_title", sa.String(200), nullable=True))
    op.add_column("ml_bot_questions", sa.Column("item_permalink", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("ml_bot_questions", "item_permalink")
    op.drop_column("ml_bot_questions", "item_title")
