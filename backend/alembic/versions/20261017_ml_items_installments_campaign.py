"""ml_items.installments_campaign: the INSTALLMENTS_CAMPAIGN sale term as a typed column

The markup of a publication needs the `INSTALLMENTS_CAMPAIGN` sale term when the item carries no campaign tag
(`pricelist_resolver`). It was extracted on every request with a JSON path over `ml_items.raw`, which forces the
server to detoast the full item body (about 7 KB, ~190 MB for the 25k items of the store): a set-wide markup request
read all of it through a 160 MB buffer cache, so each request evicted what the others needed (p95 of 3 to 13 s
against a warm p50 of 1.8 s).

The value is now written at ingest by the item mapper (`mappers.installments_campaign`) and read as a plain column.

* The column is added first (a catalog change, no rewrite) under a short `lock_timeout`, so the migration gives up
  instead of queueing behind a long transaction; the batches run under the same limit on row locks.
* The backfill is set-based and batched: `BATCH_SIZE` items by primary key range, each batch its own transaction
  (`autocommit_block`), so the ingestion workers are never blocked for more than one batch. Only rows that HAVE
  the term are updated (NULL is already the right value for the rest), and the value is computed from the target row
  itself, so a row an ingest worker rewrote meanwhile is never overwritten with a value from an older body.
* Re-runnable: running it again recomputes the same values.

Deploy order: migrate, then restart the ML workers on the new code. An item that an OLD worker rewrites between the
two keeps a stale value: a refresh whose body did not change writes no typed column (`store.apply_fetch` compares
`raw_hash`), so only a changed body, or the repair below, corrects it. The divergence check (`verification`, which
compares every typed column with a fresh fetch) reports them. To list them by hand, and to repair them:

    SELECT item_id FROM ml_items WHERE raw IS NOT NULL AND installments_campaign IS DISTINCT FROM
      (jsonb_path_query_first(raw, '$.sale_terms[*] ? (@.id == "INSTALLMENTS_CAMPAIGN").value_name') #>> '{}');

    UPDATE ml_items SET installments_campaign =
      (jsonb_path_query_first(raw, '$.sale_terms[*] ? (@.id == "INSTALLMENTS_CAMPAIGN").value_name') #>> '{}')
      WHERE raw IS NOT NULL AND installments_campaign IS DISTINCT FROM
      (jsonb_path_query_first(raw, '$.sale_terms[*] ? (@.id == "INSTALLMENTS_CAMPAIGN").value_name') #>> '{}');

Revision ID: 20261017_ml_items_installments_campaign
Revises: 20261016_ct_mlo_soh_indexes
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261017_ml_items_installments_campaign"
down_revision: Union[str, None] = "20261016_ct_mlo_soh_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BATCH_SIZE = 2000

# The very path the markup used per request: the first `value_name` of the matching term, as text.
_PATH = '$.sale_terms[*] ? (@.id == "INSTALLMENTS_CAMPAIGN").value_name'
_NEXT_BOUNDARY = sa.text(
    "SELECT max(item_id) FROM (SELECT item_id FROM ml_items WHERE item_id > :after ORDER BY item_id LIMIT :n) batch"
)
_UPDATE = sa.text(
    "UPDATE ml_items SET installments_campaign = jsonb_path_query_first(raw, CAST(:path AS jsonpath)) #>> '{}' "
    "WHERE item_id > :after AND item_id <= :last AND raw IS NOT NULL "
    "AND jsonb_path_exists(raw, CAST(:path AS jsonpath))"
)


def _update_batch(bind: sa.engine.Connection, after: str, last: str) -> None:
    bind.execute(_UPDATE, {"path": _PATH, "after": after, "last": last})


def backfill(bind: sa.engine.Connection) -> None:
    """Fill the column of every item with the term, one primary key range per statement. The ranges are walked
    with the column's default collation, the one the primary key index is in, so each batch is an index range."""
    after = ""
    while True:
        last = bind.execute(_NEXT_BOUNDARY, {"after": after, "n": BATCH_SIZE}).scalar()
        if last is None:
            return
        _update_batch(bind, after, last)
        after = last


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE ml_items ADD COLUMN IF NOT EXISTS installments_campaign text")
    with op.get_context().autocommit_block():
        # The `SET LOCAL` above ended with the DDL transaction: the batches need their own limit, so a worker that
        # holds a row for long fails the batch (the migration can be re-run) instead of hanging the deploy.
        bind = op.get_bind()
        bind.execute(sa.text("SET lock_timeout = '5s'"))
        try:
            backfill(bind)
        finally:
            bind.execute(sa.text("RESET lock_timeout"))


def downgrade() -> None:
    op.execute("ALTER TABLE ml_items DROP COLUMN IF EXISTS installments_campaign")
