"""etiquetas_envio: history of logistics changes (table + row trigger)

Revision ID: 20261201_etiquetas_logistica_historial
Revises: 20261130_tb_item_full_row
Create Date: 2026-10-27

flex-logistica-historial T2 (S1). Every change of `etiquetas_envio.logistica_id` used to overwrite the old value
(a label reassigned by mistake could not be traced, and the own Flex freight in the metrics depends on it). Now a
ROW trigger `AFTER UPDATE OF logistica_id ... WHEN (OLD IS DISTINCT FROM NEW)` inserts one row in
`etiquetas_envio_logistica_historial` per changed label, so the bulk mass assignment records one row per label
and no write path can skip it. Who and source come from the transaction-local settings `app.logistica_usuario_id`,
`app.logistica_operador_id` and `app.logistica_origen`; missing or malformed ones are recorded as NULL, never an
error. The existing `trg_order_metrics_etiquetas_envio_*` triggers are untouched (separate trigger and function).

The trigger SQL is a frozen copy of `app/services/etiquetas/logistica_historial_sql.py` (the live definition).
No backfill: the history starts with this revision.

LOCK NOTE: CREATE/DROP TRIGGER takes a SHARE ROW EXCLUSIVE lock on `etiquetas_envio` (no rewrite, no scan). Behind
an open writer it would queue and block every new writer of the table, so upgrade and downgrade run with
`lock_timeout = '5s'`: they fail fast (55P03, lock_not_available) and the deploy is retried. `env.py` runs all
pending revisions in ONE transaction, so the transaction-local setting is restored to its previous value
afterwards instead of leaking into the next revisions.
"""

from typing import List, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261201_etiquetas_logistica_historial"
down_revision: Union[str, None] = "20261130_tb_item_full_row"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "etiquetas_envio_logistica_historial"
LOCK_TIMEOUT = "5s"

# ---- Frozen copy of app/services/etiquetas/logistica_historial_sql.py ----
FUNCTION = "etiquetas_envio_logistica_historial_registrar"
TRIGGER = "trg_etiquetas_envio_logistica_historial"


def _setting_int(name: str) -> str:
    # At most 9 digits: always fits INTEGER, so a bad value can never raise.
    return (
        f"CASE WHEN current_setting('{name}', true) ~ '^[0-9]{{1,9}}$' "
        f"THEN current_setting('{name}', true)::integer END"
    )


UPGRADE_SQL: List[str] = [
    f"""
CREATE OR REPLACE FUNCTION {FUNCTION}() RETURNS TRIGGER AS $trg$
BEGIN
    INSERT INTO etiquetas_envio_logistica_historial
        (shipping_id, logistica_anterior_id, logistica_nueva_id, usuario_id, operador_id, origen)
    VALUES (
        NEW.shipping_id,
        OLD.logistica_id,
        NEW.logistica_id,
        {_setting_int("app.logistica_usuario_id")},
        {_setting_int("app.logistica_operador_id")},
        NULLIF(current_setting('app.logistica_origen', true), '')
    );
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE TRIGGER {TRIGGER}
AFTER UPDATE OF logistica_id ON etiquetas_envio
FOR EACH ROW
WHEN (OLD.logistica_id IS DISTINCT FROM NEW.logistica_id)
EXECUTE FUNCTION {FUNCTION}()
""",
]

DOWNGRADE_SQL: List[str] = [
    f"DROP TRIGGER IF EXISTS {TRIGGER} ON etiquetas_envio",
    f"DROP FUNCTION IF EXISTS {FUNCTION}()",
]
# ---- End of frozen copy ----


def _is_postgres() -> bool:
    # plpgsql trigger: Postgres only (SQLite test schemas skip it).
    return op.get_bind().dialect.name == "postgresql"


def _set_lock_timeout() -> None:
    # The previous value (session or transaction) is saved in a custom setting and restored, not reset to DEFAULT.
    op.execute("SELECT set_config('etiquetas.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")


def _restore_lock_timeout() -> None:
    op.execute("SELECT set_config('lock_timeout', current_setting('etiquetas.lock_timeout_previo'), true)")


def upgrade() -> None:
    postgres = _is_postgres()
    if postgres:
        _set_lock_timeout()  # also bounds the FK lock on `logisticas`
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shipping_id", sa.String(50), nullable=False),
        sa.Column("logistica_anterior_id", sa.Integer(), sa.ForeignKey("logisticas.id"), nullable=True),
        sa.Column("logistica_nueva_id", sa.Integer(), sa.ForeignKey("logisticas.id"), nullable=True),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("operador_id", sa.Integer(), nullable=True),
        sa.Column("origen", sa.Text(), nullable=True),
        sa.Column("cambiado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_etiq_logistica_historial_shipping", TABLE, ["shipping_id", "cambiado_en"])
    if postgres:
        for statement in UPGRADE_SQL:
            op.execute(statement)
        _restore_lock_timeout()


def downgrade() -> None:
    postgres = _is_postgres()
    if postgres:
        _set_lock_timeout()
        for statement in DOWNGRADE_SQL:
            op.execute(statement)
    op.drop_index("idx_etiq_logistica_historial_shipping", table_name=TABLE)
    op.drop_table(TABLE)
    if postgres:
        _restore_lock_timeout()
