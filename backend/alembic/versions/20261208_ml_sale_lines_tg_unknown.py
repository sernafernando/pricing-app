"""ml_sale_lines.tg_known: an unknown Total Gauss is told apart from a real 0

Revision ID: 20261208_ml_sale_lines_tg_unknown
Revises: 20261204_ml_cost_sync_give_up_column
Create Date: 2026-10-28

Métricas ML audit A3. A stored line's `tg` is 0 both when its order's Total Gauss is not resolved yet and when it
is exactly 0, and the board reads every 0 as unknown (`tg != 0`): a sale with a real Total Gauss of 0 never adds
its sell in / sell out. `tg_known` says which one it is, derived like `tg` itself (the order is settled, its
`gauss_status` is ok/provisional and its `total_gauss` is not NULL).

Existing lines keep their current meaning: `tg_known = (tg <> 0)`, the very rule the board applies today. A line
with a real 0 stored before this revision stays "unknown" until it is rewritten: the writer derives the flag from
the order's metrics, and the stored-vs-live divergence check (which compares it) rewrites the lines that differ.
No row's `tg` changes.

How, without rewriting the table: ADD COLUMN with a constant default (true) is a catalog-only change in Postgres
11+; the UPDATE then touches only the lines whose `tg` is 0; the default then becomes false (also catalog-only,
existing rows keep their value).

Why false stays as the default: `deploy.sh` migrates before it restarts the drain, so the old writer, which does not
know the column, keeps storing lines in between (the frontend build runs in that window). Without a default those
inserts would fail, and the drain retries a failed order until it is parked (`POISON_THRESHOLD`). False is the
board's "unknown": such a line only stays out of sell in / sell out until the divergence check rewrites it. The
current writer always sets the flag (it is in `sale_lines_store.COLUMNS`).

LOCK NOTE: ADD COLUMN takes an ACCESS EXCLUSIVE lock on `ml_sale_lines`, which the drain writes all day. Behind an
open writer it would queue and block every reader of the board, so upgrade and downgrade run with
`lock_timeout = '5s'` and fail fast (55P03) instead; the deploy is retried. The lock is held until the deploy's
transaction commits, so the board also waits for the UPDATE: it rewrites only the `tg = 0` lines (orders whose Total
Gauss was not resolved when stored), a small share of the table. The transaction-local setting is restored
afterwards because `env.py` runs every pending revision in one transaction.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261208_ml_sale_lines_tg_unknown"
down_revision: Union[str, None] = "20261204_ml_cost_sync_give_up_column"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_sale_lines"
COLUMN = "tg_known"
LOCK_TIMEOUT = "5s"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _set_lock_timeout() -> None:
    op.execute("SELECT set_config('ml_sale_lines.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")


def _restore_lock_timeout() -> None:
    op.execute("SELECT set_config('lock_timeout', current_setting('ml_sale_lines.lock_timeout_previo'), true)")


def upgrade() -> None:
    postgres = _is_postgres()
    if postgres:
        _set_lock_timeout()
    op.add_column(TABLE, sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.true()))
    # The board's rule until now: a 0 is an unknown Total Gauss.
    op.execute(f"UPDATE {TABLE} SET {COLUMN} = false WHERE tg = 0")
    op.alter_column(TABLE, COLUMN, server_default=sa.false())
    if postgres:
        _restore_lock_timeout()


def downgrade() -> None:
    postgres = _is_postgres()
    if postgres:
        _set_lock_timeout()
    op.drop_column(TABLE, COLUMN)
    if postgres:
        _restore_lock_timeout()
