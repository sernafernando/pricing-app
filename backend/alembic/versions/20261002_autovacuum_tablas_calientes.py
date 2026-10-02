"""per-table autovacuum thresholds for the hot tables (2% instead of 20%)

Revision ID: 20261002_autovacuum_tablas_calientes
Revises: 20261001_ix_board_reads
Create Date: 2026-10-02

Measured in production on 2026-10-02 (`pg_stat_user_tables`): the tables the
ERP syncs and the ML ingestion rewrite all day sat at 12-19% dead rows and most
had never been autovacuumed. The server default only vacuums a table once 20%
of it is dead, so these tables bloat and their visibility maps go stale: an
index-only scan on `ml_order_items_ops` fetched the heap for 3812 of 5000 rows
on a disk already saturated by reads (every backend in `DataFileRead`).

2% (vacuum and analyze) keeps them clean without changing the server-wide
defaults for every other table. `ALTER TABLE ... SET (...)` only takes a SHARE
UPDATE EXCLUSIVE lock: reads and writes keep going. `lock_timeout` makes the
deploy fail fast instead of queueing behind a running VACUUM or DDL. A table
that does not exist (e.g. an ERP mirror absent in a dev database) is skipped.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20261002_autovacuum_tablas_calientes"
down_revision: Union[str, None] = "20261001_ix_board_reads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "tb_commercial_transactions",
    "tb_item_transaction_serials",
    "tb_item_serials",
    "tb_mercadolibre_orders_shipping",
    "tb_sale_order_detail_history",
    "tb_sale_order_header_history",
    "ml_payment_charges",
    "ml_ventas_metricas",
    "ml_orders_ops",
    "ml_order_metrics",
    "ml_order_items_ops",
    "ml_venta_deducciones",
    "ml_shipments_ops",
    "ml_payments_ops",
    "tb_mercadolibre_items_publicados",
)

SETTINGS = {
    "autovacuum_vacuum_scale_factor": "0.02",
    "autovacuum_analyze_scale_factor": "0.02",
}


def _existing_tables() -> list:
    bind = op.get_bind()
    # Plain or partitioned tables only: to_regclass also resolves views,
    # sequences and indexes, which take no autovacuum storage parameters.
    query = text("SELECT relkind FROM pg_class WHERE oid = to_regclass(:t)")
    return [t for t in TABLES if bind.execute(query, {"t": t}).scalar() in ("r", "p")]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    options = ", ".join(f"{key} = {value}" for key, value in SETTINGS.items())
    for table in _existing_tables():
        op.execute(f"ALTER TABLE {table} SET ({options})")
    # SET LOCAL lasts until the transaction ends, and Alembic may run the next
    # revisions in this same transaction: give them back the default.
    op.execute("SET LOCAL lock_timeout = DEFAULT")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    keys = ", ".join(SETTINGS)
    for table in _existing_tables():
        op.execute(f"ALTER TABLE {table} RESET ({keys})")
    op.execute("SET LOCAL lock_timeout = DEFAULT")
