"""productos-costo-ppp perf round: version the tb_item_transactions LATERAL index

Revision ID: 20260727_ppp_lateral_index
Revises: 20260727_fix_llm_ids
Create Date: 2026-07-27

The PPP resolver (`app.services.costo_ppp_service.resolver_ppp_batch`) now
uses a PostgreSQL LATERAL join to pick the latest qualifying
`tb_item_transactions` row per `item_id` (see that module's docstring for the
production EXPLAIN ANALYZE numbers). That LATERAL join relies on this index
to become an index scan instead of a sequential scan per item_id.

The index was already created MANUALLY in production via
`CREATE INDEX CONCURRENTLY` (to avoid locking the table) ahead of this
migration, and is live there. This migration is written to be idempotent
(`IF NOT EXISTS`) precisely because of that — running it against production
must be a no-op, while any other environment (staging, a fresh dev DB) gets
the index created.

`CREATE INDEX CONCURRENTLY` cannot run inside a transaction block, so both
upgrade and downgrade use `op.get_context().autocommit_block()`. SQLite has
no equivalent (SQLite doesn't support CONCURRENTLY, and this app's SQLite use
is test-only via `Base.metadata.create_all`, never via Alembic) — this
migration only runs against PostgreSQL, so no SQLite branch is needed.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260727_ppp_lateral_index"
down_revision = "20260727_fix_llm_ids"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_tit_item_cd_desc"
TABLE_NAME = "tb_item_transactions"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        # This app's non-PostgreSQL usage is SQLite in tests only, which
        # never runs Alembic migrations (tests build the schema directly
        # from `Base.metadata.create_all`). Guard anyway so `alembic upgrade
        # head` never breaks on a non-PostgreSQL target.
        return

    with op.get_context().autocommit_block():
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} ON {TABLE_NAME} (item_id, it_cd DESC)")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
