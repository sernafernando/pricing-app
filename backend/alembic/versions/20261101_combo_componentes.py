"""combo_componentes: app-owned combo bill of materials, filled once from the ERP mirror

Revision ID: 20261101_combo_componentes
Revises: 20261031_sell_dirty_queue
Create Date: 2026-10-17

combos-propios C1. `combo_componentes` (`app/models/combo_componente.py`)
holds combo -> component + quantity, owned by the app. No foreign key to the
ERP mirror tables.

The upgrade fills it once from `tb_item_association` so it is usable right
after deploy. A sync handler that keeps it up to date from the ERP comes in a
following change and applies these same rules, so the first sync run finds
nothing to change:

- only rows with a positive `iasso_qty` are components (anything else is not a
  composition); a pair that appears twice holds the sum of both quantities;
- fail closed, all or nothing: if any row lacks `item_id` or `item_id_1`, has
  an unreadable quantity (NaN; `Numeric(18, 4)` cannot hold infinity), or the
  rows span more than one `comp_id` (the app-owned table has no company), the
  source cannot be trusted as the complete set of combos, so the fill copies
  nothing and the table starts empty;
- if the mirror table does not exist (it is created by the alembic chain, but
  a database bootstrapped another way may lack it), the fill is skipped.

The downgrade drops the table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_combo_componentes"
down_revision: Union[str, None] = "20261031_sell_dirty_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INITIAL_FILL = """
INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad)
SELECT item_id, item_id_1, SUM(iasso_qty)
FROM tb_item_association
WHERE iasso_qty > 0
  AND NOT EXISTS (
    SELECT 1 FROM tb_item_association
    WHERE item_id IS NULL
       OR item_id_1 IS NULL
       OR iasso_qty = 'NaN'
  )
  AND (SELECT COUNT(DISTINCT comp_id) FROM tb_item_association) <= 1
GROUP BY item_id, item_id_1
"""


def upgrade() -> None:
    op.create_table(
        "combo_componentes",
        sa.Column("combo_item_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("componente_item_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("cantidad", sa.Numeric(18, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("combo_item_id", "componente_item_id"),
        sa.CheckConstraint("cantidad > 0", name="ck_combo_componentes_cantidad_positiva"),
    )
    op.create_index("ix_combo_componentes_componente_item_id", "combo_componentes", ["componente_item_id"])
    if op.get_bind().execute(sa.text("SELECT to_regclass('tb_item_association')")).scalar() is not None:
        op.execute(_INITIAL_FILL)


def downgrade() -> None:
    op.drop_index("ix_combo_componentes_componente_item_id", table_name="combo_componentes")
    op.drop_table("combo_componentes")
