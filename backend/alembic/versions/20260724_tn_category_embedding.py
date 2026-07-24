"""tn-reconcile-publish sub-slice 3b: create tn_category_embedding (pgvector)

Revision ID: 20260724_tn_category_embedding
Revises: 8f1e9b4f9f1b
Create Date: 2026-07-24

Foundation table for the embedder-assisted TN category suggestion (design
"Category" decision): a build-once, re-runnable mirror of the TN category
tree with a 384-dim `pgvector` embedding of each category's readable path
text, queried by cosine similarity at publish time (sub-slice 3c consumes
this via the 3b suggestion endpoint).

Same Postgres-only DDL guard as `20260721_ml_bot_answer_history.py`
(`ml_bot_answer_history`'s own migration): `CREATE EXTENSION vector`, the
`vector(384)` column type, and the HNSW cosine index all require pgvector,
available only on the Postgres deploy target — the backend's CI/test DB is
SQLite (no pgvector at all), and no `alembic upgrade` is ever run against it
in CI, but this migration stays dialect-safe for any manual/local SQLite run.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_tn_category_embedding"
down_revision: Union[str, None] = "8f1e9b4f9f1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMBEDDING_DIM = 384


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tn_category_embedding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tn_category_id", sa.Integer(), nullable=False),
        sa.Column("category_path_text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.Text() if is_postgres else sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "idx_tn_category_embedding_tn_category_id",
        "tn_category_embedding",
        ["tn_category_id"],
        unique=True,
    )

    if is_postgres:
        # `embedding` is created as TEXT above only as a portable placeholder
        # (`op.create_table` has no built-in pgvector column type); fix it up
        # to the real `vector(384)` type via raw DDL, then build the HNSW
        # index (pgvector defaults: m=16, ef_construction=64 — no training
        # needed, good recall from the very first row, and the category tree
        # is small enough that exact-vs-approximate makes little difference).
        op.execute(
            f"ALTER TABLE tn_category_embedding "
            f"ALTER COLUMN embedding TYPE vector({_EMBEDDING_DIM}) "
            f"USING embedding::vector({_EMBEDDING_DIM})"
        )
        op.execute(
            "CREATE INDEX idx_tn_category_embedding_embedding_hnsw "
            "ON tn_category_embedding USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS idx_tn_category_embedding_embedding_hnsw")

    op.drop_index("idx_tn_category_embedding_tn_category_id", table_name="tn_category_embedding")
    op.drop_table("tn_category_embedding")
    # Extension is shared/cluster-wide — never dropped on downgrade.
