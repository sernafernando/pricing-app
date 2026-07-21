"""ml-bot-dynamic-fewshot: create ml_bot_answer_history (pgvector corpus)

Revision ID: 20260721_ml_bot_answer_history
Revises: 20260720_add_promo_refresh_pending
Create Date: 2026-07-21

Foundation table for the dynamic similarity-selected few-shot flywheel
(design "ml_bot_answer_history model + migration"): captures published bot
answers with a 384-dim `pgvector` embedding of the answer text, retrieved by
cosine similarity in PR3. No runtime behavior change — nothing reads/writes
this table yet (capture lands in PR2, retrieval in PR3).

Postgres-only DDL guard: `CREATE EXTENSION vector`, the `vector(384)` column
type, and the HNSW cosine index all require pgvector, which only exists on
the Postgres deploy target — the backend's CI/test DB is SQLite (no pgvector
support at all, and no `alembic upgrade` is ever run against it in CI, but
this migration is still written to be dialect-safe for any manual/local
SQLite run). Guarded on `op.get_bind().dialect.name`:
- Postgres: real `CREATE EXTENSION`, `embedding` created as `TEXT` inside
  `create_table` (Alembic has no built-in pgvector column type) then
  immediately altered to `vector(384)` via raw DDL, plus the HNSW cosine
  index.
- SQLite (or any other dialect): `embedding` is a plain `JSON` column and no
  extension/index DDL runs. The ORM model's `Vector(384)` type (via
  `pgvector.sqlalchemy`) is what's actually queried against in Postgres;
  this SQLite branch only keeps `alembic upgrade head` clean outside of
  Postgres — the app's test suite builds its schema from the ORM directly
  (`Base.metadata.create_all`, see `tests/conftest.py`'s Vector->JSON remap),
  not from this migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_ml_bot_answer_history"
down_revision: Union[str, None] = "20260720_add_promo_refresh_pending"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMBEDDING_DIM = 384


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "ml_bot_answer_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("edited_flag", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("category", sa.String(length=40), nullable=True),
        sa.Column("embedding", sa.Text() if is_postgres else sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_ml_bot_answer_history_item_id", "ml_bot_answer_history", ["item_id"])

    if is_postgres:
        # `embedding` is created as TEXT above only as a portable placeholder
        # (`op.create_table` has no built-in pgvector column type); fix it up
        # to the real `vector(384)` type via raw DDL, then build the HNSW
        # index (pgvector defaults: m=16, ef_construction=64 — no training
        # needed, good recall from the very first row).
        op.execute(
            f"ALTER TABLE ml_bot_answer_history "
            f"ALTER COLUMN embedding TYPE vector({_EMBEDDING_DIM}) "
            f"USING embedding::vector({_EMBEDDING_DIM})"
        )
        op.execute(
            "CREATE INDEX idx_ml_bot_answer_history_embedding_hnsw "
            "ON ml_bot_answer_history USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS idx_ml_bot_answer_history_embedding_hnsw")

    op.drop_index("idx_ml_bot_answer_history_item_id", table_name="ml_bot_answer_history")
    op.drop_table("ml_bot_answer_history")
    # Extension is shared/cluster-wide — never dropped on downgrade.
