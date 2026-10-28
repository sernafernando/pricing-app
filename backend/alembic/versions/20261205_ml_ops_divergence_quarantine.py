"""ml_orders_ops_cuarentena takes the activity receiver's unresolved orders off ml_ops_divergence

Revision ID: 20261205_ml_ops_divergence_quarantine
Revises: 20261204_ml_cost_sync_give_up_column
Create Date: 2026-10-27

remove-ml-divergences D2b (owner: "divergencias no debería ni existir"). When ML did not give an order back to the
activity receiver, it recorded a debt in the legacy `ml_ops_divergence` table (rows `kind='unknown'`,
`field='activity_unresolved'`), its last writer. Now the debt is a row of the order quarantine with no payload:
`raw_order` becomes nullable, the replay skips such a row (nothing to replay), and it is settled once the order lands
in `ml_orders_ops`.

The open debts (`state` open or acknowledged) are copied over (Postgres), keeping when they were detected as the first
failure. Their last attempt is now: until the worker restarts on the new code, its replay still selects every due
row, and a copied row is not due for its backoff. An order already quarantined with its payload (a write that failed)
keeps that row. A row with the JSON `null` literal (the old replay re-quarantining a copied row, its column had no
`none_as_null`) has no payload either. The legacy rows are left in place: the
table is dropped by a later revision. Downgrade rewrites the open legacy debts from the rows with no payload (debts
settled after the upgrade do not come back), removes those rows and makes `raw_order` NOT NULL again.

LOCK NOTE: DROP/SET NOT NULL take an ACCESS EXCLUSIVE lock on `ml_orders_ops_cuarentena` (SET NOT NULL also scans the
table, which is small). Behind an open writer the lock would queue and block every new reader, so upgrade and
downgrade run with `lock_timeout = '5s'` and fail fast (55P03) instead; the deploy is retried. The transaction-local
setting is restored afterwards because `env.py` runs every pending revision in one transaction.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261205_ml_ops_divergence_quarantine"
down_revision: Union[str, None] = "20261204_ml_cost_sync_give_up_column"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_orders_ops_cuarentena"
LOCK_TIMEOUT = "5s"
# activity_receiver_service.UNRESOLVED_ERROR, frozen here
UNRESOLVED_ERROR = "[transient] get_order returned nothing to the activity receiver"
# A row with nothing to replay (`ingestion_service.has_no_payload`).
NO_PAYLOAD = "(q.raw_order IS NULL OR q.raw_order = 'null'::jsonb)"
UNRESOLVED_DEBT = "d.kind = 'unknown' AND d.field = 'activity_unresolved' AND d.state IN ('open', 'acknowledged')"

COPY_FROM_DIVERGENCE = f"""
INSERT INTO {TABLE} (order_id, raw_order, error, intentos, primera_falla_at, ultimo_intento_at)
SELECT d.order_id, NULL, :error, 1, d.detected_at, now()
FROM ml_ops_divergence d
WHERE {UNRESOLVED_DEBT}
ON CONFLICT (order_id) DO NOTHING
"""

# A debt settled after the upgrade (its quarantine row deleted) must not come back from its pre-upgrade row. The
# debt of an order quarantined with its payload was never copied, so it is left as it was.
DELETE_LEGACY_DEBTS = f"""
DELETE FROM ml_ops_divergence d
WHERE {UNRESOLVED_DEBT}
  AND NOT EXISTS (SELECT 1 FROM {TABLE} q WHERE q.order_id = d.order_id AND NOT {NO_PAYLOAD})
"""

# Detected when the order first failed. A closed (resolved, ignored) legacy row of the same order is refreshed, the way
# the old writer refreshed any row.
COPY_TO_DIVERGENCE = f"""
INSERT INTO ml_ops_divergence (order_id, kind, field, detected_at)
SELECT q.order_id, 'unknown', 'activity_unresolved', q.primera_falla_at
FROM {TABLE} q
WHERE {NO_PAYLOAD}
ON CONFLICT (order_id, kind, field) DO UPDATE SET detected_at = EXCLUDED.detected_at
"""

DELETE_UNRESOLVED = f"DELETE FROM {TABLE} q WHERE {NO_PAYLOAD}"
# Elsewhere (no JSONB, no debts copied back) only SQL NULL blocks the NOT NULL.
DELETE_UNRESOLVED_PORTABLE = f"DELETE FROM {TABLE} WHERE raw_order IS NULL"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _set_lock_timeout() -> None:
    op.execute(
        "SELECT set_config('ml_divergence_quarantine.lock_timeout_previo', current_setting('lock_timeout'), true)"
    )
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")


def _restore_lock_timeout() -> None:
    op.execute(
        "SELECT set_config('lock_timeout', current_setting('ml_divergence_quarantine.lock_timeout_previo'), true)"
    )


def _raw_order_nullable(nullable: bool) -> None:
    op.alter_column(TABLE, "raw_order", existing_type=postgresql.JSONB(astext_type=sa.Text()), nullable=nullable)


def upgrade() -> None:
    postgres = _is_postgres()
    if postgres:
        _set_lock_timeout()
    _raw_order_nullable(True)
    if postgres:
        op.get_bind().execute(sa.text(COPY_FROM_DIVERGENCE), {"error": UNRESOLVED_ERROR})
        _restore_lock_timeout()


def downgrade() -> None:
    postgres = _is_postgres()
    if postgres:
        _set_lock_timeout()
        op.execute(DELETE_LEGACY_DEBTS)
        op.execute(COPY_TO_DIVERGENCE)
    op.execute(DELETE_UNRESOLVED if postgres else DELETE_UNRESOLVED_PORTABLE)
    _raw_order_nullable(False)
    if postgres:
        _restore_lock_timeout()
