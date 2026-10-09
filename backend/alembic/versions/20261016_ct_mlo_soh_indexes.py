"""tb_commercial_transactions: partial indexes on (mlo_id, comp_id) and (ct_soh_id, comp_id)

Production plans (2026-10-09; ~604k rows, 18M lifetime seq scans, 3.6T rows read) showed:

* the ML metrics join `LEFT JOIN tb_commercial_transactions tct ON tct.comp_id = tmlod.comp_id AND
  tct.mlo_id = tmlod.mlo_id` (agregar_metricas_ml_*.py, ventas_ml.py) as `Hash Right Join -> Seq Scan`;
* the Seriales/Prearmado lookups by `ct_soh_id` as `Parallel Seq Scan`.

Column order: `comp_id` is a near-constant (a single company), so it filters nothing; the discriminating column
goes first. That also lets `ct_soh_id = :x` without `comp_id` (seriales_shared RMA query) use the same index.
`comp_id` stays as second column so the equality pair of the joins is answered from the index alone.
The predicates match the NULL-heavy columns (most rows are not ML sales / have no sale order) and keep the
indexes small.

`CREATE INDEX CONCURRENTLY` (outside a transaction, so writes of the ERP sync are never blocked) with a short
`lock_timeout` so it gives up instead of queueing behind a long transaction. A build that fails midway leaves
the index INVALID, and `IF NOT EXISTS` would then skip it: an invalid leftover is dropped first.

`SET lock_timeout` is session-level, so alembic must connect to Postgres directly, not through PgBouncer in
transaction mode (same as every CONCURRENTLY index migration of this repo).

Revision ID: 20261016_ct_mlo_soh_indexes
Revises: 20261015_proveedor_direccion_numero
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261016_ct_mlo_soh_indexes"
down_revision: Union[str, None] = "20261015_proveedor_direccion_numero"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = (
    ("ix_tct_mlo_id_comp_id", "(mlo_id, comp_id) WHERE mlo_id IS NOT NULL"),
    ("ix_tct_ct_soh_id_comp_id", "(ct_soh_id, comp_id) WHERE ct_soh_id IS NOT NULL"),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, definition in _INDEXES:
                invalid = (
                    op.get_bind()
                    .execute(
                        sa.text(
                            "SELECT NOT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                            "JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "WHERE c.relname = :name AND n.nspname = current_schema()"
                        ),
                        {"name": name},
                    )
                    .scalar()
                )
                if invalid:
                    op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
                op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON tb_commercial_transactions {definition}")
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, _definition in _INDEXES:
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
        finally:
            op.execute("RESET lock_timeout")
