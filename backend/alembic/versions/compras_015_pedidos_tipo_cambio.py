"""compras 015 — agregar tipo_cambio a pedidos_compra

Revision ID: compras_015_pedidos_tc
Revises: compras_014_vfactvig
Create Date: 2026-04-21

Agrega columna `tipo_cambio Numeric(18,6) NULL` a `pedidos_compra` para
registrar la cotización ARS/USD vigente al momento del pedido (Batch B
del plan de UX de compras, feedback del usuario: "no me pusiste campo
para tipo de cambio").

Semántica:
  - `moneda='USD'` + `tipo_cambio IS NOT NULL` → TC explícito del pedido.
  - `moneda='USD'` + `tipo_cambio IS NULL`     → usar TC del día al consultar.
  - `moneda='ARS'` + `tipo_cambio IS NULL`     → N/A.
  - `moneda='ARS'` + `tipo_cambio IS NOT NULL` → rechazado por servicio (HTTP 400).

No agregamos CHECK constraint en v1 para preservar flexibilidad al
recargar datos históricos. La validación vive en `pedidos_service`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_015_pedidos_tc"
down_revision: Union[str, None] = "compras_014_vfactvig"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pedidos_compra",
        sa.Column("tipo_cambio", sa.Numeric(18, 6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pedidos_compra", "tipo_cambio")
