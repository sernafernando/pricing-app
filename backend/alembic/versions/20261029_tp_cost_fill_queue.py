"""tp_cost_fill_queue + list-8 triggers that wake the TP cost fill worker

Revision ID: 20261029_tp_cost_fill_queue
Revises: 20261029_ml_ads_campaigns
Create Date: 2026-10-16

metricas-ml-tplink-mode P2 (worker half). Sales frozen without a TP-Link cost
(no list-8 price) are filled once when a list-8 price shows up. These triggers
queue the item and `pg_notify('tp_cost_fill')`; the `tp_cost.fill` handler
drains the queue. Fired by:
- `tb_item_cost_list`, coslis_id 8: insert, or an update that actually changes
  `coslis_price`/`curr_id`;
- `tb_item_cost_list_history`, coslis_id 8: insert (the resolver reads the
  history, which the ERP sync writes after the current list), or an update
  that actually changes `iclh_price`/`curr_id` (the ERP correcting a past price).

Frozen copy of `app/services/ml_orders_ingestion/tp_cost_fill.py`'s
`UPGRADE_SQL`/`DOWNGRADE_SQL` (that module is the live definition). The
downgrade drops everything this created.

LOCK NOTE: CREATE TRIGGER takes a SHARE ROW EXCLUSIVE lock on the two ERP cost
tables for an instant; the ERP sync that writes them retries on its next run.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261029_tp_cost_fill_queue"
down_revision: Union[str, None] = "20261029_ml_ads_campaigns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE = [
    """
CREATE TABLE IF NOT EXISTS tp_cost_fill_queue (
    item_id INTEGER PRIMARY KEY,
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
)
""",
    """
CREATE OR REPLACE FUNCTION tp_cost_fill_enqueue() RETURNS TRIGGER AS $trg$
BEGIN
    INSERT INTO tp_cost_fill_queue (item_id) VALUES (NEW.item_id)
    ON CONFLICT (item_id) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    PERFORM pg_notify('tp_cost_fill', '');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER trg_tp_cost_fill_list_insert
AFTER INSERT ON tb_item_cost_list
FOR EACH ROW WHEN (NEW.coslis_id = 8 AND NEW.item_id IS NOT NULL)
EXECUTE FUNCTION tp_cost_fill_enqueue()
""",
    """
CREATE TRIGGER trg_tp_cost_fill_list_update
AFTER UPDATE OF coslis_price, curr_id ON tb_item_cost_list
FOR EACH ROW WHEN (
    NEW.coslis_id = 8 AND NEW.item_id IS NOT NULL
    AND (OLD.coslis_price IS DISTINCT FROM NEW.coslis_price OR OLD.curr_id IS DISTINCT FROM NEW.curr_id)
)
EXECUTE FUNCTION tp_cost_fill_enqueue()
""",
    """
CREATE TRIGGER trg_tp_cost_fill_history_insert
AFTER INSERT ON tb_item_cost_list_history
FOR EACH ROW WHEN (NEW.coslis_id = 8 AND NEW.item_id IS NOT NULL)
EXECUTE FUNCTION tp_cost_fill_enqueue()
""",
    """
CREATE TRIGGER trg_tp_cost_fill_history_update
AFTER UPDATE OF iclh_price, curr_id ON tb_item_cost_list_history
FOR EACH ROW WHEN (
    NEW.coslis_id = 8 AND NEW.item_id IS NOT NULL
    AND (OLD.iclh_price IS DISTINCT FROM NEW.iclh_price OR OLD.curr_id IS DISTINCT FROM NEW.curr_id)
)
EXECUTE FUNCTION tp_cost_fill_enqueue()
""",
]

_DOWNGRADE = [
    "DROP TRIGGER IF EXISTS trg_tp_cost_fill_history_update ON tb_item_cost_list_history",
    "DROP TRIGGER IF EXISTS trg_tp_cost_fill_history_insert ON tb_item_cost_list_history",
    "DROP TRIGGER IF EXISTS trg_tp_cost_fill_list_update ON tb_item_cost_list",
    "DROP TRIGGER IF EXISTS trg_tp_cost_fill_list_insert ON tb_item_cost_list",
    "DROP FUNCTION IF EXISTS tp_cost_fill_enqueue()",
    "DROP TABLE IF EXISTS tp_cost_fill_queue",
]


def _is_postgres() -> bool:
    # plpgsql triggers and pg_notify: Postgres only (SQLite test schemas skip it).
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        for statement in _UPGRADE:
            op.execute(statement)


def downgrade() -> None:
    if _is_postgres():
        for statement in _DOWNGRADE:
            op.execute(statement)
