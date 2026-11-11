"""sell_in_bonos_marca: a brand bonus may carry a category

Revision ID: 20261111_sell_in_bono_marca_categoria
Revises: 20261110_pedido_compra_facturas
Create Date: 2026-11-11

SISO S3 (owner): "Que se puedan combinar marca y categoría porque hoy no se puede, si quiero aplicar a los routers
solo de tp-link no puedo." A bonus with `alcance = 'marca'` may set `categoria`: it then reaches only that brand's
products of that category. Only the CHECK changes; no row is touched.

Downgrade restores the old CHECK, which fails while a brand bonus carries a category (it never drops data).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261111_sell_in_bono_marca_categoria"
down_revision: Union[str, None] = "20261110_pedido_compra_facturas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOMBRE = "ck_sell_in_bonos_marca_campos_segun_alcance"
RESTO = (
    "OR (alcance = 'categoria' AND categoria IS NOT NULL AND marca IS NULL AND pedido_id IS NULL) "
    "OR (alcance = 'modelos' AND marca IS NULL AND categoria IS NULL AND pedido_id IS NULL) "
    "OR (alcance = 'factura' AND marca IS NULL AND categoria IS NULL)"
)
NUEVO = f"(alcance = 'marca' AND marca IS NOT NULL AND pedido_id IS NULL) {RESTO}"
VIEJO = f"(alcance = 'marca' AND marca IS NOT NULL AND categoria IS NULL AND pedido_id IS NULL) {RESTO}"


def upgrade() -> None:
    op.execute("SELECT set_config('lock_timeout', '5s', false)")
    op.drop_constraint(NOMBRE, "sell_in_bonos_marca", type_="check")
    op.create_check_constraint(NOMBRE, "sell_in_bonos_marca", NUEVO)


def downgrade() -> None:
    op.execute("SELECT set_config('lock_timeout', '5s', false)")
    op.drop_constraint(NOMBRE, "sell_in_bonos_marca", type_="check")
    op.create_check_constraint(NOMBRE, "sell_in_bonos_marca", VIEJO)
