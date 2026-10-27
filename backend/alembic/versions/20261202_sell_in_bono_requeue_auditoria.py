"""Requeue the brand bonus keys parked by the `tipoaccion` audit error.

Revision ID: 20261202_sell_in_bono_requeue_auditoria
Revises: 20261201_ml_venta_impuesto_tratamiento
Create Date: 2026-10-27

The bonus worker writes its audit rows in one multi-row INSERT, which cast
`tipo_accion` to a `tipoaccion` type production never had, so every reconcile
failed and its key parked after `MAX_ATTEMPTS`. With the model fixed, a parked
key only retries when its row changes again: this puts back the keys that
failed for that reason (same reset the queue triggers do) and wakes the worker.
Data only; nothing to undo.
"""

from alembic import op

revision = "20261202_sell_in_bono_requeue_auditoria"
down_revision = "20261201_ml_venta_impuesto_tratamiento"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "UPDATE sell_in_bono_dirty SET enqueued_at = now(), attempts = 0, last_error = NULL "
        "WHERE last_error LIKE '%tipoaccion%'"
    )
    op.execute("SELECT pg_notify('sell_in_bono_dirty', '')")


def downgrade() -> None:
    pass
