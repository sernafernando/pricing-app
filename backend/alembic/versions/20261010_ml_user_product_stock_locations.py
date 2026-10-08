"""ml_user_product_stock: typed per-location quantities (Full vs own stock)

Revision ID: 20261010_ml_user_product_stock_locations
Revises: 20261009_om_dirty_priority_index
Create Date: 2026-10-10

`ml_user_product_stock` only kept `total_quantity`; the split lives in `raw->'locations'`
(`[{type, quantity}]`). Two typed columns make it queryable without parsing JSONB per row:

- `full_quantity`: the `meli_facility` quantity (stock in Full).
- `own_quantity`: `selling_address` + `seller_warehouse` (the seller's own stock).

Flex is not a stock location in MercadoLibre. NULL means "no readable `locations` list" (no body, or
`locations` is not a list); 0 means the list is valid and holds none of that type, the same rules as
`map_user_product_stock`, which fills the columns from now on.

The ALTER is metadata-only (nullable, no default) but takes an ACCESS EXCLUSIVE lock on a table the
sweep writes to, hence `lock_timeout`. The lock lasts until the transaction commits, so the backfill runs
OUTSIDE it: `autocommit_block` commits the ALTER first, then each batch commits on its own (no long
transaction accumulating row locks against the writer). The batches walk the text primary key in order,
so a retry after a crash simply recomputes the same values.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261010_ml_user_product_stock_locations"
down_revision: Union[str, None] = "20261009_om_dirty_priority_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "ml_user_product_stock"
_BATCH = 5000
_FULL = "= 'meli_facility'"
_OWN = "IN ('selling_address', 'seller_warehouse')"


def _sum_of(type_filter: str) -> str:
    """Sum of the integer `quantity` of the object entries whose `type` matches.

    Same rule as the Python mapper for every payload ML sends: strings, booleans, decimals and junk entries
    are ignored. Two theoretical differences, neither seen in any capture: an integer of 10 or more digits
    (the mapper adds it, here it is skipped rather than overflowing the INTEGER column) and a float-notation
    integer such as `1e2` (jsonb normalizes it to `100`, which counts; the mapper reads a float and skips it).
    The type filter is the only difference between the two sums.
    """
    return (
        "(SELECT COALESCE(SUM((loc->>'quantity')::integer), 0) "
        "FROM jsonb_array_elements(raw->'locations') AS loc "
        "WHERE jsonb_typeof(loc) = 'object' AND jsonb_typeof(loc->'quantity') = 'number' "
        f"AND loc->>'quantity' ~ '^-?[0-9]{{1,9}}$' AND loc->>'type' {type_filter})"
    )


_BACKFILL = sa.text(
    f"UPDATE {_TABLE} SET full_quantity = {_sum_of(_FULL)}, own_quantity = {_sum_of(_OWN)} "
    "WHERE user_product_id = ANY(:ids) AND jsonb_typeof(raw->'locations') = 'array'"
)
_NEXT_BATCH = sa.text(
    f"SELECT user_product_id FROM {_TABLE} WHERE user_product_id > :last ORDER BY user_product_id LIMIT :n"
)


def _backfill() -> None:
    bind = op.get_bind()
    last = ""
    while True:
        ids = [r[0] for r in bind.execute(_NEXT_BATCH, {"last": last, "n": _BATCH})]
        if not ids:
            return
        bind.execute(_BACKFILL, {"ids": ids})
        last = ids[-1]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(_TABLE, sa.Column("full_quantity", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("own_quantity", sa.Integer(), nullable=True))

    # `autocommit_block` commits the ALTER above (releasing its lock) before the backfill runs.
    with op.get_context().autocommit_block():
        _backfill()


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column(_TABLE, "own_quantity")
    op.drop_column(_TABLE, "full_quantity")
