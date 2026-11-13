"""productos_erp: index on the normalized brand and category, so the planner knows how many rows they keep

The Publicaciones ML filters on the product's brand, category and PM (`view/filters.py::normalized_text`:
`upper(trim(coalesce(col, '')))`, the key the tree and the PM pairs use) compare an EXPRESSION, and Postgres keeps
no statistics for an expression unless an index is built on it. Without them it guesses that a PM's (brand,
category) pairs keep a handful of rows where they keep thousands, and builds nested loops sized for that guess.
That guess, with the promo set as an index condition, was the PM + promo DEAL `statement_timeout` of 2026-11-12
(fixed in the query itself, `filters._item_in`); with the statistics, the worst statement of a 12-pair PM + promo
on the 25k volume seed goes from 1.7 s to 0.5 s.

The index is mostly there for its statistics (ANALYZE gathers them for indexed expressions); its expressions
must stay identical to `normalized_text`, which a volume test pins. `ANALYZE productos_erp` runs right after the
build so the statistics exist before the next query, not after the next autovacuum.

`CREATE INDEX CONCURRENTLY` with a short `lock_timeout`, as `20261011_ml_items_last_trigger_index` (an INVALID
leftover of a failed build is dropped first; alembic must connect directly, not through PgBouncer in transaction
mode).

Revision ID: 20261112_productos_erp_normalized_brand_category_index
Revises: 20261112_tactical_facturas_pendientes
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_productos_erp_normalized_brand_category_index"
down_revision: Union[str, None] = "20261112_tactical_facturas_pendientes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = "ix_productos_erp_normalized_marca_categoria"
EXPRESSIONS = "(upper(trim(coalesce(marca, '')))), (upper(trim(coalesce(categoria, ''))))"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            invalid = (
                op.get_bind()
                .execute(
                    sa.text(
                        "SELECT NOT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE c.relname = :name AND n.nspname = current_schema()"
                    ),
                    {"name": INDEX},
                )
                .scalar()
            )
            if invalid:
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON productos_erp ({EXPRESSIONS})")
            op.execute("ANALYZE productos_erp")
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
        finally:
            op.execute("RESET lock_timeout")
