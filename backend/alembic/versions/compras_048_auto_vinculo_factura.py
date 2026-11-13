"""compras 048 — auto-vínculo ERP outcome on factura documentos

Revision ID: compras_048_auto_vinculo_factura
Revises: 20261113_permiso_mejores_ofertas_pms
Create Date: 2026-11-13

Persists the result of `auto_vincular_por_constancia_cargada` so Administración
can filter pedidos whose cargada constancia did not get a unique ERP CT link
(mirror lag or ambiguous docnumber).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_048_auto_vinculo_factura"
down_revision: Union[str, None] = "20261113_permiso_mejores_ofertas_pms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pedido_factura_documentos",
        sa.Column("auto_vinculo_estado", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "pedido_factura_documentos",
        sa.Column("auto_vinculo_intentado_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_pedido_factura_documentos_auto_vinculo_pendiente",
        "pedido_factura_documentos",
        ["auto_vinculo_estado"],
        postgresql_where=sa.text(
            "cargada = true AND auto_vinculo_estado IN ('sin_match', 'ambiguo', 'sin_mapeo')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pedido_factura_documentos_auto_vinculo_pendiente",
        table_name="pedido_factura_documentos",
    )
    op.drop_column("pedido_factura_documentos", "auto_vinculo_intentado_at")
    op.drop_column("pedido_factura_documentos", "auto_vinculo_estado")
