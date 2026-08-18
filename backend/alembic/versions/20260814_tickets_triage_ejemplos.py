"""tickets-triage-feedback PR3: create tickets_triage_ejemplos (pgvector)

Revision ID: 20260814_tickets_triage_ejemplos
Revises: 20260813_propuesta_corregida
Create Date: 2026-08-14

Foundation table for the best-effort correction capture flywheel (design
"Best-effort correction capture behind a flag"): captures a genuine human
correction of an AI triage proposal (severidad/urgencia only) with a
384-dim `pgvector` embedding of the ticket's original text, for future
similarity-based few-shot retrieval. No runtime behavior change — capture
is dark-launched behind `TICKETS_TRIAGE_EJEMPLOS_CAPTURE` (default False)
and nothing reads this table yet.

HNSW is forward insurance at <1000 rows, not evidence of scale — do not let
its presence be misread later as a sign this table is already large.

Same Postgres-only DDL guard as `20260721_ml_bot_answer_history.py` /
`20260724_tn_category_embedding.py`: `CREATE EXTENSION vector`, the
`vector(384)` column type, and the HNSW cosine index all require pgvector,
available only on the Postgres deploy target — the backend's CI/test DB is
SQLite (no pgvector at all), and no `alembic upgrade` is ever run against it
in CI, but this migration stays dialect-safe for any manual/local SQLite run.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_tickets_triage_ejemplos"
down_revision: Union[str, None] = "20260813_propuesta_corregida"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMBEDDING_DIM = 384


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tickets_triage_ejemplos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("propuesta_id", sa.Integer(), sa.ForeignKey("tickets_propuestas_ia.id"), nullable=False),
        sa.Column("campo", sa.String(length=20), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("valor_ia", sa.String(length=20), nullable=False),
        sa.Column("valor_corregido", sa.String(length=20), nullable=False),
        sa.Column("embedding", sa.Text() if is_postgres else sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("propuesta_id", name="uq_tickets_triage_ejemplos_propuesta_id"),
        sa.CheckConstraint("campo IN ('severidad','urgencia')", name="ck_tickets_triage_ejemplos_campo"),
    )

    op.create_index("ix_tickets_triage_ejemplos_ticket_id", "tickets_triage_ejemplos", ["ticket_id"])
    op.create_index(
        "ix_tickets_triage_ejemplos_campo_active",
        "tickets_triage_ejemplos",
        ["campo", "active"],
    )

    if is_postgres:
        # `embedding` is created as TEXT above only as a portable placeholder
        # (`op.create_table` has no built-in pgvector column type); fix it up
        # to the real `vector(384)` type via raw DDL, then build the HNSW
        # index (pgvector defaults: m=16, ef_construction=64 — no training
        # needed, good recall from the very first row). This table starts
        # empty and grows one row per genuine correction — HNSW here is
        # forward insurance at low row counts, not evidence of scale.
        op.execute(
            f"ALTER TABLE tickets_triage_ejemplos "
            f"ALTER COLUMN embedding TYPE vector({_EMBEDDING_DIM}) "
            f"USING embedding::vector({_EMBEDDING_DIM})"
        )
        op.execute(
            "CREATE INDEX idx_tickets_triage_ejemplos_embedding_hnsw "
            "ON tickets_triage_ejemplos USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS idx_tickets_triage_ejemplos_embedding_hnsw")

    op.drop_index("ix_tickets_triage_ejemplos_campo_active", table_name="tickets_triage_ejemplos")
    op.drop_index("ix_tickets_triage_ejemplos_ticket_id", table_name="tickets_triage_ejemplos")
    op.drop_table("tickets_triage_ejemplos")
    # Extension is shared/cluster-wide — never dropped on downgrade.
