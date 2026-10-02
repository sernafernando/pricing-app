"""index on tb_mercadolibre_items_publicados.mlp_publicationid (CONCURRENTLY)

Revision ID: 20261001_ix_mlp_publicationid
Revises: 20260930_ml_ops_resincronizar
Create Date: 2026-10-01

ODD `metricas-ml-tablero` T1: the Ventas ML store filter resolves each sold
item's MLA to its official store through
`tb_mercadolibre_items_publicados.mlp_publicationid`, inside a correlated
EXISTS that runs once per candidate group. The model declares `index=True` on
that column, but no migration ever created it, so whether production has it
depends on how the table was first built. This makes it explicit.

Same name the model's `index=True` produces; a database that already has it
VALID is untouched. One that has it INVALID (an earlier `CREATE INDEX
CONCURRENTLY` interrupted midway leaves the name taken by an index Postgres
never uses, and `IF NOT EXISTS` would happily keep it) gets it dropped and
built again -- `pg_index.indisvalid` decides. `CONCURRENTLY` (outside the transaction,
`autocommit_block`) so the ERP sync keeps writing while it builds -- same
precedent as `20260427_add_idx_mlp_official_store_id.py`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_ix_mlp_publicationid"
down_revision: Union[str, None] = "20260930_ml_ops_resincronizar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = "ix_tb_mercadolibre_items_publicados_mlp_publicationid"


_VALIDITY = sa.text(
    "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
    "WHERE c.relname = :name AND pg_table_is_visible(c.oid)"
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        valid = op.get_bind().execute(_VALIDITY, {"name": INDEX}).scalar()
        if valid is True:
            return
        if valid is False:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
        op.execute(f"CREATE INDEX CONCURRENTLY {INDEX} ON tb_mercadolibre_items_publicados (mlp_publicationid)")


def downgrade() -> None:
    # Deliberately a no-op: the index may predate this migration (created by
    # the model's `index=True`), and dropping it would take away something
    # this migration never added.
    pass
