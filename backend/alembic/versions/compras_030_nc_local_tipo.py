"""compras_030 — tipo en notas_credito_local (ND/NC variance circuit)

Revision ID: compras_030_nc_local_tipo
Revises: compras_029_pedido_tipo_cambio_original
Create Date: 2026-05-20

Feature F2 — ND/NC Variance Circuit:

Agrega `tipo` a `notas_credito_local` para distinguir Notas de Crédito
(tipo='credito', reducen deuda, generan HABER en CC) de Notas de Débito
(tipo='debito', aumentan deuda, generan DEBE en CC).

  * String(8) NOT NULL con server_default 'credito'.
  * Las filas existentes quedan como 'credito' (backfill automático via
    server_default — preserva la semántica actual: NC → HABER, sin cambio).
  * CHECK constraint ck_ncs_local_tipo: tipo IN ('credito','debito').

El signo contable al imputar pasa a ser determinado por `tipo`:
  - tipo='credito' → HABER (reduce deuda con el proveedor) — idéntico a hoy.
  - tipo='debito'  → DEBE  (aumenta deuda con el proveedor).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "compras_030_nc_local_tipo"
down_revision = "compras_029_pedido_tipo_cambio_original"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notas_credito_local",
        sa.Column(
            "tipo",
            sa.String(8),
            nullable=False,
            server_default="credito",
        ),
    )
    op.create_check_constraint(
        "ck_ncs_local_tipo",
        "notas_credito_local",
        "tipo IN ('credito','debito')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ncs_local_tipo", "notas_credito_local", type_="check")
    op.drop_column("notas_credito_local", "tipo")
