"""sell_out_campana_items: a product's own amount per unit inside a sell-out campaign

Revision ID: 20261207_sell_out_campana_items
Revises: 20261206_offsets_migracion_pendientes
Create Date: 2026-10-27

sell-in-sell-out T22b (S25). Owner: "sell in y sell out deberían permitir agrupados, así que si no lo está
permitiendo es un error nuestro". A legacy grouped offset gives each product ITS OWN amount under ONE shared cap; a
`por_unidad` campaign already has one cap for all its groups, and now each product it reaches may carry its own
`monto_unit` (same NUMERIC(18, 2), in the campaign currency, > 0). A product without a row gets the campaign's
`monto_unit`. The allocator (`app.services.sell_out.tope`) reads it.

- UNIQUE (campana_id, item_id): one amount per product and campaign; it also indexes `campana_id`.
- `item_id` has NO foreign key, like `sell_out_consumos.item_id` and `sell_in_bono_items.item_id`: the campaigns
  service checks the product is in the campaign's reach.
- Deleting the campaign deletes its amounts (CASCADE); campaigns are voided, never deleted, anyway.

A new, empty table: no lock on an existing one beyond the FK's on `sell_out_campanas`. The downgrade drops it; both
steps are idempotent.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261207_sell_out_campana_items"
down_revision: Union[str, None] = "20261206_offsets_migracion_pendientes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sell_out_campana_items (
    id BIGSERIAL PRIMARY KEY,
    campana_id BIGINT NOT NULL REFERENCES sell_out_campanas (id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL,
    monto_unit NUMERIC(18, 2) NOT NULL,
    CONSTRAINT uq_sell_out_campana_items_campana_item UNIQUE (campana_id, item_id),
    CONSTRAINT ck_sell_out_campana_items_monto_positivo CHECK (monto_unit > 0)
)
"""


def upgrade() -> None:
    op.execute(CREATE_TABLE)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sell_out_campana_items")
